import pickle
import random
import time
from typing import Optional

import discord
from discord import Embed, app_commands
from discord.app_commands import locale_str as _T
from discord.ext import commands
from pokemontcgsdk import Card, Set

import config
from src.colors import GREEN, RED
from src.components.paginated_embed import PaginatedEmbed
from src.entities.quest_entity import QuestType
from src.services.localization_service import LocalizationService
from src.services.quest_service import QuestService
from src.services.rarity_service import RarityService
from src.services.settings_service import SettingsService
from src.services.type_service import TypeService
from src.services.user_service import UserService
from src.utils import discord_tools
from src.utils.discord_tools import set_booster_kind_autocomplete, set_booster_kinds

TIER_0_RARITIES = {"Rare"}
TIER_1_RARITIES = {"Rare Holo"}
TIER_2_RARITIES = {"Rare Holo EX", "Rare Holo GX", "Rare Holo V", "Rare BREAK"}
TIER_3_RARITIES = {"Radiant Rare", "Rare Holo LV.X", "Rare Holo VMAX", "Rare ACE", "Rare Ultra", "Amazing Rare",
                   "Rare Prime", "Rare Prism Star", "Rare Shining", "Rare Shiny"}
TIER_4_RARITIES = {"LEGEND", "Rare Holo Star", "Rare Rainbow", "Rare Secret", "Rare Shiny GX",
                   "Rare Holo VSTAR"}
TIER_DROP_RATES = [
    40,
    30,
    20,
    8,
    2,
]


class BoosterCog(commands.Cog):
    CARDS_PICKLE_FILE_LOCATION = "data/cards.p"

    def __init__(self, bot: commands.Bot, settings_service: SettingsService,
                 localization_service: LocalizationService, user_service: UserService, rarity_service: RarityService,
                 type_service: TypeService, quest_service: QuestService) -> None:
        self.bot = bot
        self._log_channel = None
        self.settings_service = settings_service
        self._t = localization_service.get_string
        self.user_service = user_service
        self.rarity_service = rarity_service
        self.type_service = type_service
        self.quest_service = quest_service
        self.sets: list[Set] = Set.all()
        self.cards_by_rarity: dict[str, list[Card]] = BoosterCog._compute_all_cards()

    @property
    def log_channel(self):
        if self._log_channel is None:
            self._log_channel = self.bot.get_channel(config.LOG_CHANNEL_ID)
        return self._log_channel

    @staticmethod
    def _filter_cards_for_rarities(cards: list[Card], rarities: set[str]) -> list[Card]:
        filtered_cards = []
        for card in cards:
            if card.rarity in rarities:
                filtered_cards.append(card)
        return filtered_cards

    @staticmethod
    def _compute_all_cards() -> dict[str, list[Card]]:
        cards: list[Card] = pickle.load(open(BoosterCog.CARDS_PICKLE_FILE_LOCATION, "rb"))
        # TODO: find out why some cards don't have any rarity and define what should be the default rarity for them
        cards_with_rarity = list(filter(lambda card: card.rarity is not None, cards))
        return {
            "common": BoosterCog._filter_cards_for_rarities(cards_with_rarity, {"Common"}),
            "uncommon": BoosterCog._filter_cards_for_rarities(cards_with_rarity, {"Uncommon"}),
            "tier_0": BoosterCog._filter_cards_for_rarities(cards_with_rarity, TIER_0_RARITIES),
            "tier_1": BoosterCog._filter_cards_for_rarities(cards_with_rarity, TIER_1_RARITIES),
            "tier_2": BoosterCog._filter_cards_for_rarities(cards_with_rarity, TIER_2_RARITIES),
            "tier_3": BoosterCog._filter_cards_for_rarities(cards_with_rarity, TIER_3_RARITIES),
            "tier_4": BoosterCog._filter_cards_for_rarities(cards_with_rarity, TIER_4_RARITIES),
            "promo": BoosterCog._filter_cards_for_rarities(cards_with_rarity, {"Promo"})
        }

    def _get_card_type_display(self, card: Card) -> str:
        if card.types is None or len(card.types) == 0:
            return ""
        return f"[{self.type_service.get_type(card.types[0].lower()).emoji}]"

    def _display_full_booster_in_embed(self, card: Card, embed: Embed, is_new: bool):
        emojis = {emoji.name: str(emoji) for emoji in self.bot.emojis}
        rarity_emoji = "" if (rarity := self.rarity_service.get_rarity(
            card.rarity.lower())) is None else rarity.emoji
        type_emoji = self._get_card_type_display(card)
        is_new_label = emojis["new"] if is_new else ""
        embed.add_field(name=f"{card.name} {is_new_label}",
                        value=f"{card.id} {type_emoji}\n `{card.rarity} {rarity_emoji}`\n ~ {card.set.name} ~")

    def _format_card_for_embed(self, card: Card, user_language_id: int, is_new: bool):
        emojis = {emoji.name: str(emoji) for emoji in self.bot.emojis}
        formatted_id = f"**ID**: {card.id}"
        formatted_rarity = f"**{self._t(user_language_id, 'common.rarity').capitalize()}**: {card.rarity}"
        formatted_set = f"**{self._t(user_language_id, 'common.set').capitalize()}**: {card.set.name} ({card.set.series})"
        entry_card = {
            "name": card.name,
            "value": f"{formatted_id}\n{formatted_rarity}\n{formatted_set}",
            "image": card.images.large if card.images.large else card.images.small
        }
        if is_new:
            entry_card["value"] += f"\n{emojis['new']}"
        return entry_card

    def _draw_rare_card(self, set_id: Optional[str] = None) -> Card:
        rare_pool = []
        while len(rare_pool) == 0:
            card_tier = random.choices(["tier_0", "tier_1", "tier_2", "tier_3", "tier_4"], weights=TIER_DROP_RATES)[0]
            rare_pool = self.cards_by_rarity[card_tier]
            if set_id is not None:
                rare_pool = list(filter(lambda card: card.set.id == set_id, rare_pool))
        return random.choice(rare_pool)

    @staticmethod
    def _formatted_tier_list(rarity_tier: set[str]) -> str:
        return "\n* ".join(rarity_tier)

    def _generate_booster_cards(self, set_id: Optional[str] = None) -> list[Card]:
        drawn_cards = []

        common_pool = self.cards_by_rarity["common"]
        uncommon_pool = self.cards_by_rarity["uncommon"]

        if set_id is not None:
            common_pool = list(filter(lambda card: card.set.id == set_id, common_pool))
            uncommon_pool = list(filter(lambda card: card.set.id == set_id, uncommon_pool))

        # Draw the 5 common cards
        for _ in range(5):
            card = random.choice(common_pool)
            drawn_cards.append(card)

        # Draw the 3 uncommon cards
        uncommon_upgrade_triggered = False
        for _ in range(3):
            if not uncommon_upgrade_triggered and random.random() < config.UNCOMMON_UPGRADE_RATE:
                uncommon_upgrade_triggered = True
                card = self._draw_rare_card(set_id)
            else:
                card = random.choice(uncommon_pool)
            drawn_cards.append(card)

        # Draw the rare or higher card
        card = self._draw_rare_card(set_id)
        drawn_cards.append(card)

        return drawn_cards

    def _generate_promo_booster_cards(self) -> list[Card]:
        drawn_cards = []

        # Draw the 3 Promo cards
        for _ in range(3):
            card = random.choice(self.cards_by_rarity["promo"])
            drawn_cards.append(card)

        return drawn_cards

    def _build_paginated_booster(self, formatted_cards, user_language_id, interaction):
        paginated_embed = PaginatedEmbed(interaction, formatted_cards, True, user_language_id, 1,
                                         title=f"---------- {self._t(user_language_id, 'booster_cmd.title')} ----------",
                                         discord_user=interaction.user)
        return paginated_embed

    @app_commands.command(name=_T("booster_cmd-name"), description=_T("booster_cmd-desc"))
    async def booster_command(self, interaction: discord.Interaction, with_image: Optional[bool] = None,
                              use_booster_stock: Optional[bool] = False) -> None:
        user = self.user_service.get_and_update_user(interaction.user, interaction.locale)
        user_language_id = user.settings.language_id

        if user.is_banned:
            await interaction.response.send_message(self._t(user_language_id, 'common.user_banned'))
            return

        if use_booster_stock or user.cooldowns.timestamp_for_next_basic_booster > time.time():
            if user.boosters_quantity > 0 and (not user.settings.only_use_action_from_stock_with_option
                                               or use_booster_stock):
                self.user_service.consume_booster(user.id, "Basic")
            elif use_booster_stock:
                await interaction.response.send_message(self._t(user_language_id, 'booster_cmd.no_boosters_in_stock'))
                return
            else:
                discord_formatted_timestamp = discord_tools.timestamp_to_relative_time_format(
                    user.cooldowns.timestamp_for_next_basic_booster)
                await interaction.response.send_message(
                    f"{self._t(user_language_id, 'common.booster_cooldown')} {discord_formatted_timestamp}")
                return
        else:
            self.user_service.reset_basic_booster_cooldown(user.id)

        drawn_cards = self._generate_booster_cards()
        drawn_card_ids = list(map(lambda drawn_card: drawn_card.id.lower(), drawn_cards))

        accomplished_quests = self.user_service.update_progress_on_quests(user.id, QuestType.BOOSTER)
        self.user_service.add_cards_to_collection(user.id, drawn_card_ids)

        await self.log_channel.send(
            f"{user.id} ({user.name_tag}) opened a basic booster containing {drawn_card_ids}")
        if with_image is None:
            with_image = user.settings.booster_opening_with_image
        if with_image:
            formatted_cards = [self._format_card_for_embed(card, user_language_id,
                                                           user.count_quantity_of_card(card.id) == 0)
                               for card in drawn_cards]

            paginated_embed = PaginatedEmbed(interaction, formatted_cards, True, user_language_id, 1,
                                             title=f"---------- {self._t(user_language_id, 'booster_cmd.title')} ----------",
                                             discord_user=interaction.user)
            await interaction.response.send_message(embed=paginated_embed.embed, view=paginated_embed.view)
        else:
            embed = Embed(
                title=f"---------- {self._t(user_language_id, 'booster_cmd.title')} ----------",
                color=GREEN)
            embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)

            for card in drawn_cards:
                self._display_full_booster_in_embed(card, embed, user.count_quantity_of_card(card.id) == 0)

            await interaction.response.send_message(embed=embed)

        for quest in accomplished_quests:
            await interaction.followup.send(self._t(user_language_id, 'common.quest_accomplished').format(
                quest_name=self.quest_service.compute_quest_description(quest, user_language_id)))

    @app_commands.command(name=_T("promo_booster_cmd-name"), description=_T("promo_booster_cmd-desc"))
    async def promo_booster_command(self, interaction: discord.Interaction, with_image: Optional[bool] = None,
                                    use_booster_stock: Optional[bool] = False) -> None:
        user = self.user_service.get_and_update_user(interaction.user, interaction.locale)
        user_language_id = user.settings.language_id

        if user.is_banned:
            await interaction.response.send_message(self._t(user_language_id, 'common.user_banned'))
            return

        if use_booster_stock or user.cooldowns.timestamp_for_next_promo_booster > time.time():
            if user.promo_boosters_quantity > 0 and (not user.settings.only_use_action_from_stock_with_option or
                                                     use_booster_stock):
                self.user_service.consume_booster(user.id, "Promo")
            elif use_booster_stock:
                await interaction.response.send_message(
                    self._t(user_language_id, 'promo_booster_cmd.no_boosters_in_stock'))
                return
            else:
                discord_formatted_timestamp = discord_tools.timestamp_to_relative_time_format(
                    user.cooldowns.timestamp_for_next_promo_booster)
                await interaction.response.send_message(
                    f"{self._t(user_language_id, 'common.promo_booster_cooldown')} {discord_formatted_timestamp}")
                return
        else:
            self.user_service.reset_promo_booster_cooldown(user.id)

        drawn_cards = self._generate_promo_booster_cards()
        drawn_card_ids = list(map(lambda drawn_card: drawn_card.id.lower(), drawn_cards))

        self.user_service.add_cards_to_collection(user.id, drawn_card_ids)

        await self.log_channel.send(
            f"{user.id} ({user.name_tag}) opened a Promo booster containing {drawn_card_ids}")
        if with_image is None:
            with_image = user.settings.booster_opening_with_image
        if with_image:
            formatted_cards = [self._format_card_for_embed(card, user_language_id, card.id not in user.cards.keys())
                               for card in drawn_cards]

            paginated_embed = PaginatedEmbed(interaction, formatted_cards, True, user_language_id, 1,
                                             title=f"---------- {self._t(user_language_id, 'booster_cmd.title')} ----------",
                                             discord_user=interaction.user)

            await interaction.response.send_message(embed=paginated_embed.embed, view=paginated_embed.view)
        else:
            embed = Embed(
                title=f"---------- {self._t(user_language_id, 'promo_booster_cmd.title')} ----------",
                color=RED)
            embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)

            for card in drawn_cards:
                self._display_full_booster_in_embed(card, embed, card.id not in user.cards.keys())

            await interaction.response.send_message(embed=embed)

    @app_commands.command(name=_T("set_booster_cmd-name"), description=_T("set_booster_cmd-desc"))
    @app_commands.autocomplete(kind=set_booster_kind_autocomplete)
    async def set_booster_command(self, interaction: discord.Interaction, kind: str,
                                  with_image: Optional[bool] = None) -> None:
        user = self.user_service.get_and_update_user(interaction.user, interaction.locale)
        user_language_id = user.settings.language_id

        if user.is_banned:
            await interaction.response.send_message(self._t(user_language_id, 'common.user_banned'))
            return

        if kind not in set_booster_kinds:
            await interaction.response.send_message(self._t(user_language_id, 'common.invalid_input'))
            return

        if kind in user.set_boosters_quantity and user.set_boosters_quantity[kind] > 0:
            self.user_service.consume_booster(user.id, kind)
        else:
            await interaction.response.send_message(self._t(user_language_id,
                                                            'set_booster_cmd.no_boosters_in_stock').format(set_id=kind))
            return

        drawn_cards = self._generate_booster_cards(kind)
        drawn_card_ids = list(map(lambda drawn_card: drawn_card.id.lower(), drawn_cards))

        accomplished_quests = self.user_service.update_progress_on_quests(user.id, QuestType.BOOSTER)
        self.user_service.add_cards_to_collection(user.id, drawn_card_ids)

        await self.log_channel.send(
            f"{user.id} ({user.name_tag}) opened a {kind} booster containing {drawn_card_ids}")

        if with_image is None:
            with_image = user.settings.booster_opening_with_image
        if with_image:
            formatted_cards = [self._format_card_for_embed(card, user_language_id,
                                                           user.count_quantity_of_card(card.id) == 0)
                               for card in drawn_cards]

            paginated_embed = PaginatedEmbed(interaction, formatted_cards, True, user_language_id, 1,
                                             title=f"---------- {self._t(user_language_id, 'set_booster_cmd.title')} ----------",
                                             discord_user=interaction.user)
            await interaction.response.send_message(embed=paginated_embed.embed, view=paginated_embed.view)
        else:
            embed = Embed(
                title=f"---------- {self._t(user_language_id, 'set_booster_cmd.title')} ----------",
                color=GREEN)
            embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)

            for card in drawn_cards:
                self._display_full_booster_in_embed(card, embed, user.count_quantity_of_card(card.id) == 0)

            await interaction.response.send_message(embed=embed)

        for quest in accomplished_quests:
            await interaction.followup.send(self._t(user_language_id, 'common.quest_accomplished').format(
                quest_name=self.quest_service.compute_quest_description(quest, user_language_id)))

    @app_commands.command(name=_T("drop_rates_cmd-name"),
                          description=_T("drop_rates_cmd-desc"))
    async def drop_rates_command(self, interaction: discord.Interaction) -> None:
        user_language_id = self.settings_service.get_user_language_id(interaction.user)

        embed = Embed(
            title=f"---------- {self._t(user_language_id, 'drop_rates_cmd.title')} ----------",
            description=self._t(user_language_id, 'drop_rates_cmd.description'),
            color=GREEN
        )

        embed.add_field(name=f"Tier 0 - {TIER_DROP_RATES[0]}%".ljust(20, ""),
                        value=f"* {BoosterCog._formatted_tier_list(TIER_0_RARITIES)}")
        embed.add_field(name=f"Tier 1 - {TIER_DROP_RATES[1]}%".ljust(20, ""),
                        value=f"* {BoosterCog._formatted_tier_list(TIER_1_RARITIES)}")
        embed.add_field(name=f"Tier 2 - {TIER_DROP_RATES[2]}%".ljust(5, ""),
                        value=f"* {BoosterCog._formatted_tier_list(TIER_2_RARITIES)}")
        embed.add_field(name=f"Tier 3 - {TIER_DROP_RATES[3]}%".ljust(5, ""),
                        value=f"* {BoosterCog._formatted_tier_list(TIER_3_RARITIES)}")
        embed.add_field(name=f"Tier 4 - {TIER_DROP_RATES[4]}%".ljust(5, ""),
                        value=f"* {BoosterCog._formatted_tier_list(TIER_4_RARITIES)}")

        await interaction.response.send_message(embed=embed)

import pickle
from pathlib import Path
from typing import Sequence

from src.entities.suggestion_entity import SuggestionEntity
from src.repositories.suggestion_repository import SuggestionRepository


class PickleFileSuggestionRepository(SuggestionRepository):
    PICKLE_FILE_LOCATION = "data/suggestions.p"

    def __init__(self):
        Path(PickleFileSuggestionRepository.PICKLE_FILE_LOCATION).touch(exist_ok=True)

    @staticmethod
    def _load_pickle_file() -> dict[str, SuggestionEntity]:
        try:
            suggestions = pickle.load(open(PickleFileSuggestionRepository.PICKLE_FILE_LOCATION, "rb"))
        except EOFError:
            suggestions = {}
        return suggestions

    @staticmethod
    def _save_pickle_file(content: dict[str, SuggestionEntity]) -> None:
        pickle.dump(content, open(PickleFileSuggestionRepository.PICKLE_FILE_LOCATION, "wb"))

    def get_all(self) -> Sequence[SuggestionEntity]:
        suggestions_by_id = PickleFileSuggestionRepository._load_pickle_file()
        return list(suggestions_by_id.values())

    def save_suggestion(self, suggestion: SuggestionEntity) -> bool:
        suggestions = PickleFileSuggestionRepository._load_pickle_file()
        suggestions[suggestion.id] = suggestion
        PickleFileSuggestionRepository._save_pickle_file(suggestions)
        return True

    def remove_suggestion(self, suggestion_id: str) -> bool:
        suggestions = PickleFileSuggestionRepository._load_pickle_file()
        try:
            del suggestions[suggestion_id]
        except KeyError:
            return False
        PickleFileSuggestionRepository._save_pickle_file(suggestions)
        return True

    def add_up_vote_to(self, user_id: int, suggestion_id: str) -> bool:
        suggestions = PickleFileSuggestionRepository._load_pickle_file()
        suggestions[suggestion_id].up_votes.add(user_id)
        PickleFileSuggestionRepository._save_pickle_file(suggestions)
        return True

    def add_down_vote_to(self, user_id: int, suggestion_id: str) -> bool:
        suggestions = PickleFileSuggestionRepository._load_pickle_file()
        suggestions[suggestion_id].down_votes.add(user_id)
        PickleFileSuggestionRepository._save_pickle_file(suggestions)
        return True

from app.services.categories import (
    KNOWN_CATEGORIES,
    TIME_GROUP_CODES,
    TIME_GROUPS,
    normalize_time_group,
)


EXPECTED_CODES = {
    "sleep",
    "prayer",
    "quran",
    "hadith_religious",
    "dhikr",
    "food",
    "hygiene",
    "study",
    "ai_projects",
    "sport",
    "youtube_news",
    "road",
    "work",
    "children_study",
    "family_time",
    "relationships",
    "entertainment",
    "no_data",
    "waste",
}


def test_time_groups_have_stable_unique_codes_and_metadata() -> None:
    assert len(TIME_GROUPS) == 19
    assert TIME_GROUP_CODES == EXPECTED_CODES
    assert len({group.code for group in TIME_GROUPS}) == len(TIME_GROUPS)
    assert all(group.label and group.description for group in TIME_GROUPS)


def test_time_group_normalization_is_safe() -> None:
    assert normalize_time_group(" Prayer ") == "prayer"
    assert normalize_time_group("unknown-group") == "no_data"
    assert normalize_time_group(None) == "no_data"


def test_legacy_categories_remain_compatible() -> None:
    assert KNOWN_CATEGORIES == {
        "work",
        "family",
        "health",
        "prayer",
        "personal",
        "other",
    }


if __name__ == "__main__":
    test_time_groups_have_stable_unique_codes_and_metadata()
    test_time_group_normalization_is_safe()
    test_legacy_categories_remain_compatible()
    print("PASS: time groups dictionary and legacy category compatibility")

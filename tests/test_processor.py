"""
Tests for processor.py — pure data logic, no DB, no real files on disk
(except fixture files and tmp_path for encoding tests).
"""
import pytest
from pathlib import Path

import processor

FIXTURES = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# parse_elapsed_time
# ---------------------------------------------------------------------------

class TestParseElapsedTime:
    def test_normal(self):
        assert processor.parse_elapsed_time("01:30.500") == pytest.approx(90.5)

    def test_zero(self):
        assert processor.parse_elapsed_time("00:00.000") == pytest.approx(0.0)

    def test_no_minutes(self):
        assert processor.parse_elapsed_time("00:45.123") == pytest.approx(45.123)

    def test_sentinel_negative_one(self):
        assert processor.parse_elapsed_time("-1") is None

    def test_sentinel_tag_doesnt_exist(self):
        assert processor.parse_elapsed_time("Tag doesnt exist") is None

    def test_empty_string(self):
        assert processor.parse_elapsed_time("") is None

    def test_none(self):
        assert processor.parse_elapsed_time(None) is None

    def test_whitespace_only(self):
        assert processor.parse_elapsed_time("   ") is None


# ---------------------------------------------------------------------------
# parse_players_csv
# ---------------------------------------------------------------------------

class TestParsePlayersCsv:
    def test_columns_and_index(self):
        df = processor.parse_players_csv(FIXTURES / "players.csv")
        assert list(df.columns) == ["DisplayName", "PointsEarned", "LastLevelJoined"]
        assert df.index.name == "Username"

    def test_player_data(self):
        df = processor.parse_players_csv(FIXTURES / "players.csv")
        assert "player1" in df.index
        assert df.loc["player1", "DisplayName"] == "Player One"
        assert df.loc["player1", "PointsEarned"] == 100
        assert df.loc["player1", "LastLevelJoined"] == 1

    def test_trailing_comma_does_not_shift_columns(self):
        # Key regression: trailing comma on data rows must not shift all columns right.
        # If broken, PointsEarned would be in the DisplayName slot (a string, not int).
        df = processor.parse_players_csv(FIXTURES / "players.csv")
        # pandas returns np.int64; check it is numeric (not str) and has the correct value.
        import numbers
        assert isinstance(df.loc["player1", "PointsEarned"], numbers.Number)
        assert df.loc["player1", "PointsEarned"] == 100

    def test_utf16_bom(self, tmp_path):
        src = (FIXTURES / "players.csv").read_text(encoding="utf-8")
        csv_path = tmp_path / "players_utf16.csv"
        csv_path.write_bytes(src.encode("utf-16"))  # produces \xff\xfe BOM
        df = processor.parse_players_csv(str(csv_path))
        assert "player1" in df.index
        assert df.loc["player1", "DisplayName"] == "Player One"


# ---------------------------------------------------------------------------
# parse_level_csv
# ---------------------------------------------------------------------------

class TestParseLevelCsv:
    def test_required_columns_present(self):
        df = processor.parse_level_csv(FIXTURES / "level.csv")
        for col in ["CurrentLevel", "ElapsedTime", "CurrentTopTiltee", "LevelExp", "LevelPassed"]:
            assert col in df.columns

    def test_level_passed_parsed_as_bool(self):
        df = processor.parse_level_csv(FIXTURES / "level.csv")
        # pandas/numpy returns np.True_; use == rather than `is` for identity check.
        assert df.iloc[0]["LevelPassed"] == True  # noqa: E712

    def test_level_failed_parsed_as_bool(self):
        df = processor.parse_level_csv(FIXTURES / "level_failed.csv")
        assert df.iloc[0]["LevelPassed"] == False  # noqa: E712

    def test_level_number(self):
        df = processor.parse_level_csv(FIXTURES / "level.csv")
        assert df.iloc[0]["CurrentLevel"] == 1


# ---------------------------------------------------------------------------
# _extract_level_data
# ---------------------------------------------------------------------------

class TestExtractLevelData:
    def test_level_number(self):
        players_df = processor.parse_players_csv(FIXTURES / "players.csv")
        level_df   = processor.parse_level_csv(FIXTURES / "level.csv")
        data = processor._extract_level_data(players_df, level_df)
        assert data["level_number"] == 1

    def test_players_filtered_to_current_level(self):
        # players_level2 has player1+2 at level1 and player3 at level2; current level is 2
        players_df = processor.parse_players_csv(FIXTURES / "players_level2.csv")
        level_df   = processor.parse_level_csv(FIXTURES / "level2.csv")
        data = processor._extract_level_data(players_df, level_df)
        usernames = [p["username"] for p in data["players"]]
        assert "player3" in usernames
        assert "player1" not in usernames
        assert "player2" not in usernames

    def test_survived_true_when_points_earned_positive(self):
        players_df = processor.parse_players_csv(FIXTURES / "players.csv")
        level_df   = processor.parse_level_csv(FIXTURES / "level.csv")
        data = processor._extract_level_data(players_df, level_df)
        by_user = {p["username"]: p for p in data["players"]}
        assert by_user["player1"]["survived"] is True   # PointsEarned=100
        assert by_user["player2"]["survived"] is False  # PointsEarned=0

    def test_top_tiltee_username(self):
        players_df = processor.parse_players_csv(FIXTURES / "players.csv")
        level_df   = processor.parse_level_csv(FIXTURES / "level.csv")
        data = processor._extract_level_data(players_df, level_df)
        assert data["top_tiltee_username"] == "player1"

    def test_top_tiltee_none_when_empty(self):
        players_df = processor.parse_players_csv(FIXTURES / "players.csv")
        level_df   = processor.parse_level_csv(FIXTURES / "level_failed.csv")
        data = processor._extract_level_data(players_df, level_df)
        assert data["top_tiltee_username"] is None

    def test_elapsed_time_converted_to_seconds(self):
        players_df = processor.parse_players_csv(FIXTURES / "players.csv")
        level_df   = processor.parse_level_csv(FIXTURES / "level.csv")
        data = processor._extract_level_data(players_df, level_df)
        assert data["elapsed_time"] == pytest.approx(45.123)



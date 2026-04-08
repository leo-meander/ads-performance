"""Tests for name parsing engine."""

from app.services.parse_utils import parse_adset_metadata, parse_campaign_metadata


class TestParseCampaignMetadata:
    def test_solo_tof(self):
        result = parse_campaign_metadata("Mason_TPE_[TOF] Landing page Solo UK")
        assert result["ta"] == "Solo"
        assert result["funnel_stage"] == "TOF"

    def test_couple_tof(self):
        result = parse_campaign_metadata("Mason_OSK_[TOF] Sales_Landing Page Couple Sakura_AU")
        assert result["ta"] == "Couple"
        assert result["funnel_stage"] == "TOF"

    def test_friend_mof(self):
        result = parse_campaign_metadata("Mason_SGN_[MOF] Retargeting Friend VN")
        assert result["ta"] == "Friend"
        assert result["funnel_stage"] == "MOF"

    def test_group_bof(self):
        result = parse_campaign_metadata("Mason_TPE_[BOF] Booking Group TW")
        assert result["ta"] == "Group"
        assert result["funnel_stage"] == "BOF"

    def test_business(self):
        result = parse_campaign_metadata("Mason_SGN_[TOF] Business Traveler Campaign")
        assert result["ta"] == "Business"
        assert result["funnel_stage"] == "TOF"

    def test_case_insensitive_ta(self):
        result = parse_campaign_metadata("Mason_SGN_[TOF] SOLO campaign")
        assert result["ta"] == "Solo"

    def test_case_insensitive_funnel(self):
        result = parse_campaign_metadata("Mason_SGN_[tof] Solo campaign")
        assert result["funnel_stage"] == "TOF"

    def test_unknown_ta(self):
        result = parse_campaign_metadata("Mason_SGN_[TOF] Landing Page General")
        assert result["ta"] == "Unknown"
        assert result["funnel_stage"] == "TOF"

    def test_unknown_funnel(self):
        result = parse_campaign_metadata("Mason_SGN Solo campaign no bracket")
        assert result["ta"] == "Solo"
        assert result["funnel_stage"] == "Unknown"

    def test_both_unknown(self):
        result = parse_campaign_metadata("Generic campaign name here")
        assert result["ta"] == "Unknown"
        assert result["funnel_stage"] == "Unknown"

    def test_empty_name(self):
        result = parse_campaign_metadata("")
        assert result["ta"] == "Unknown"
        assert result["funnel_stage"] == "Unknown"

    def test_none_name(self):
        result = parse_campaign_metadata(None)
        assert result["ta"] == "Unknown"
        assert result["funnel_stage"] == "Unknown"

    def test_first_ta_match_wins(self):
        """If name contains multiple TAs, first match from whitelist wins."""
        result = parse_campaign_metadata("Mason_SGN_[TOF] Solo Couple Mixed")
        assert result["ta"] == "Solo"

    def test_no_bracket_no_funnel(self):
        """Funnel tags without brackets should not match."""
        result = parse_campaign_metadata("Mason_SGN TOF Solo campaign")
        assert result["funnel_stage"] == "Unknown"


class TestParseAdsetMetadata:
    def test_tw(self):
        result = parse_adset_metadata("TW_25_M&F_ZH_Broad")
        assert result["country"] == "TW"

    def test_au(self):
        result = parse_adset_metadata("AU_25-44_M&F_New LP")
        assert result["country"] == "AU"

    def test_jp(self):
        result = parse_adset_metadata("JP_25-44_M&F_ENG")
        assert result["country"] == "JP"

    def test_sg(self):
        result = parse_adset_metadata("SG_25-34_M&F_ENG")
        assert result["country"] == "SG"

    def test_us(self):
        result = parse_adset_metadata("US_25-44_M&F_Lookalike")
        assert result["country"] == "US"

    def test_lowercase_input(self):
        result = parse_adset_metadata("vn_25_M&F_ZH")
        assert result["country"] == "VN"

    def test_empty_name(self):
        result = parse_adset_metadata("")
        assert result["country"] == "Unknown"

    def test_none_name(self):
        result = parse_adset_metadata(None)
        assert result["country"] == "Unknown"

    def test_no_underscore(self):
        result = parse_adset_metadata("TWMIXED")
        assert result["country"] == "TW"  # First 2 chars

    def test_single_char(self):
        result = parse_adset_metadata("A_something")
        assert result["country"] == "Unknown"  # Only 1 char, not valid

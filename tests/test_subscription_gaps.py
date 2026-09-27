from apps.api.repository import explain_subscription_gaps
from packages.providers.market import SubscriptionCategory


def test_verified_category_calculates_its_own_denominator():
    category = SubscriptionCategory(bid_shares=2500, offered_shares=1000)
    result = explain_subscription_gaps({"categories": {"retail": category.model_dump(mode="json")}})
    assert result["categories"]["retail"]["multiple"] == "2.5000"
    assert "gap_note" not in result["categories"]["retail"]


def test_missing_allocations_never_use_total_ipo_shares():
    result = explain_subscription_gaps(
        {
            "categories": {
                "total": {"multiple": "0.5", "offered_shares": "1000000"},
                "retail": {"multiple": None, "bid_shares": "147200", "offered_shares": "0"},
            }
        }
    )
    for key in ["retail", "qib", "nii"]:
        assert result["categories"][key]["multiple"] is None
        assert "not used as a substitute" in result["categories"][key]["gap_note"]
    assert result["categories"]["total"]["multiple"] == "0.5"
    assert "gap_note" not in result["categories"]["total"]


def test_actual_zero_demand_is_not_a_missing_allocation():
    result = explain_subscription_gaps(
        {"categories": {"qib": {"multiple": "0.0000", "offered_shares": "1000"}}}
    )
    assert result["categories"]["qib"]["multiple"] == "0.0000"
    assert "gap_note" not in result["categories"]["qib"]

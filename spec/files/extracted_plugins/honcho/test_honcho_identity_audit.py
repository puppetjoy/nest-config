from nest_honcho.identity_audit import (
    audit_peer_card_identity_relations,
    extract_alias_candidates,
)


def test_extract_alias_candidates_from_identity_alias_fact():
    card = ["IDENTITY: Aliases: Talon, Star", "Pronouns: they/them"]

    candidates = extract_alias_candidates(card)

    assert [candidate.value for candidate in candidates] == ["Talon", "Star"]
    assert candidates[0].fact == "IDENTITY: Aliases: Talon, Star"


def test_joy_talon_star_false_alias_regression_proposes_typed_relationship():
    card = [
        "IDENTITY: Name: Joyful Lee",
        "IDENTITY: Aliases: Talon, Star",
        "IDENTITY: Pronouns: they/them",
        "Joy works with AI agents Talon, Star, and Beryl on Hermes/Nest operations",
    ]

    report = audit_peer_card_identity_relations(
        card,
        peer="Joy",
        known_entity_names=["Talon", "Star", "Beryl"],
        evidence_texts=[
            "Joy said Talon and Star are agents they work with, not names they use for themselves.",
        ],
    )

    assert report.review_required is True
    assert [finding.value for finding in report.findings] == ["Talon", "Star"]
    assert all(finding.code == "identity_relation_conflation" for finding in report.findings)
    assert "IDENTITY: Aliases: Talon, Star" not in report.proposed_card
    assert "Works with AI agents including Talon, Star, and Beryl" in report.proposed_card


def test_real_alias_with_strong_evidence_is_not_removed_even_if_unknown():
    card = ["IDENTITY: Name: Joyful Lee", "IDENTITY: Aliases: Joy"]

    report = audit_peer_card_identity_relations(
        card,
        peer="user",
        evidence_texts=["The user said: call me Joy."],
    )

    assert report.findings == ()
    assert report.review_required is False
    assert "IDENTITY: Aliases: Joy" in report.proposed_card


def test_mixed_alias_fact_keeps_unflagged_alias_for_review_safety():
    card = ["IDENTITY: Aliases: Joy, Talon"]

    report = audit_peer_card_identity_relations(
        card,
        peer="user",
        known_entity_names=["Talon"],
        evidence_texts=["Joy works with Talon the assistant."],
    )

    assert [finding.value for finding in report.findings] == ["Talon"]
    assert "IDENTITY: Aliases: Joy" in report.proposed_card
    assert "IDENTITY: Aliases: Joy, Talon" not in report.proposed_card

"""Which products a question names (E5 B4). Invented product names."""

from limespec.scope import naming, scope_of

NAMES = [
    "Silic8 AD2",
    "Silic8 MPL1 Primer",
    "Silic8 Silguard",
    "Warmshell Meshcoat",
    "Warmshell 660 Mesh",
    "Warmshell Board Adhesive",
    "Lime Mortar",
    "Natural Lime Mortar",
    "Ashlar Lime Mortar",
]


def test_a_passage_belongs_to_the_page_its_title_starts_with() -> None:
    assert scope_of("Silic8 AD2 — Data Sheet") == "Silic8 AD2"
    assert scope_of("Silic8 AD2") == "Silic8 AD2"


def test_a_product_is_named_by_its_distinctive_words_spacing_ignored() -> None:
    named = naming(NAMES)

    # "silic8" is in three names, so it names none alone; "ad2" is AD2's own word.
    assert named("is silic8 ad2 good for lath repair") == ["Silic8 AD2"]
    assert named("what about Silic8?") == []
    assert named("Warmshell Mesh Coat over boards") == ["Warmshell Meshcoat"]
    assert named("warmshell 660 mesh or meshcoat") == [
        "Warmshell Meshcoat",
        "Warmshell 660 Mesh",
    ]


def test_a_name_of_only_common_words_names_nothing() -> None:
    named = naming(NAMES)

    # "lime" and "mortar" are in three names; "Lime Mortar" has no word of its own.
    assert named("which lime mortar for pointing") == []
    assert named("natural lime mortar strength") == ["Natural Lime Mortar"]

"""Stage-1 parity gate: vendored fork vs a Rockwell native export.

Runs only when real project files are supplied via environment variables
(they are too large / proprietary to commit):

    PLC_DOCGEN_TEST_ACD     path to a .ACD file
    PLC_DOCGEN_TEST_NATIVE  path to the matching Studio native export .L5X

Asserts the fork's offline conversion is a documentation superset of the
native export: identical rung counts, >=99% of native rung comments, and
every native tag description present.
"""

import os

import pytest

ACD = os.environ.get("PLC_DOCGEN_TEST_ACD")
NATIVE = os.environ.get("PLC_DOCGEN_TEST_NATIVE")

pytestmark = pytest.mark.skipif(
    not (ACD and NATIVE and os.path.exists(ACD) and os.path.exists(NATIVE)),
    reason="PLC_DOCGEN_TEST_ACD / PLC_DOCGEN_TEST_NATIVE not provided",
)


def _text_of(el):
    t = (el.text or "").strip()
    if t:
        return t
    for child in el:
        ct = (child.text or "").strip()
        if ct:
            return ct
    return ""


def _inventory(path):
    from lxml import etree

    root = etree.parse(path).getroot()
    rung_comments = {}
    for prog in root.iter("Program"):
        for routine in prog.iter("Routine"):
            for rung in routine.iter("Rung"):
                c = rung.find("Comment")
                if c is not None and _text_of(c):
                    rung_comments[
                        (prog.get("Name"), routine.get("Name"), rung.get("Number"))
                    ] = _text_of(c)
    tag_descriptions = {}
    for tags in root.iter("Tags"):
        parent = tags.getparent()
        scope = parent.get("Name") if parent is not None else "?"
        for tag in tags.findall("Tag"):
            d = tag.find("Description")
            if d is not None and _text_of(d):
                tag_descriptions[(scope, tag.get("Name"))] = _text_of(d)
    return {
        "rungs": sum(1 for _ in root.iter("Rung")),
        "rung_comments": rung_comments,
        "tag_descriptions": tag_descriptions,
    }


@pytest.fixture(scope="module")
def converted(tmp_path_factory):
    from l5x_analyzer.acd_offline_convert import convert_acd_to_l5x

    out = tmp_path_factory.mktemp("parity") / "candidate.l5x"
    result = convert_acd_to_l5x(ACD, str(out))
    assert result.get("success"), f"conversion failed: {result.get('error')}"
    return _inventory(str(out))


@pytest.fixture(scope="module")
def native():
    return _inventory(NATIVE)


def test_rung_count_matches_native(converted, native):
    assert converted["rungs"] == native["rungs"]


def test_rung_comments_recovered(converted, native):
    native_keys = set(native["rung_comments"])
    cand_keys = set(converted["rung_comments"])
    missing = native_keys - cand_keys
    assert len(missing) <= max(1, len(native_keys) // 100), (
        f"missing {len(missing)}/{len(native_keys)} rung comments: "
        f"{sorted(missing)[:5]}"
    )


def test_tag_descriptions_superset_of_native(converted, native):
    missing = set(native["tag_descriptions"]) - set(converted["tag_descriptions"])
    assert not missing, f"missing tag descriptions: {sorted(missing)[:10]}"

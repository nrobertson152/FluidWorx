import pytest

from fluidworx.units import Units, find_cylinder, find_quantity, parse_entry, parse_number


def test_conversions_round_trip():
    u = Units("us")
    assert u.from_si("pressure", 6894.757) == pytest.approx(1.0)
    assert u.to_si("flow", 1.0) == pytest.approx(6.309e-5, rel=1e-3)
    assert Units("metric").fmt("pressure", 160e5) == "160 bar"


@pytest.mark.parametrize("text,q,value", [("10 L/min", "flow", 1e-2 / 60), ("160 bar", "pressure", 160e5),
                                          ("3000 psi", "pressure", 3000 * 6894.757), ("relief 2,5 bar", "pressure", 2.5e5),
                                          ("32 cc/rev", "displacement", 32e-6)])
def test_labels(text, q, value):
    assert find_quantity(text, q) == pytest.approx(value)


def test_label_without_a_unit_is_not_guessed():
    assert find_quantity("V2", "pressure") is None
    assert find_quantity("10 L/min", "pressure") is None


def test_cylinder_labels():
    assert find_cylinder("63/36x300") == pytest.approx({"bore": .063, "rod": .036, "stroke": .3})
    assert find_cylinder("2.5/1.25 x 12 in") == pytest.approx({"bore": .0635, "rod": .03175, "stroke": .3048})
    assert find_cylinder("Lift cylinder") == {}
    assert find_cylinder("10 L/min") == {}
    assert find_cylinder("20/50x100") == {}       # a rod can't be larger than its bore


@pytest.mark.parametrize("text,v", [("30/2", 15), ("2*pi", 6.28318), ("1,234.5", 1234.5), (" 7 ", 7)])
def test_inputs_accept_math_like_caldera(text, v):
    assert parse_number(text) == pytest.approx(v, rel=1e-4)


@pytest.mark.parametrize("bad", ["", "abc", "__import__('os')", "1/0", "9**99**99", "1e999", "open('x')"])
def test_inputs_refuse_anything_else(bad):
    with pytest.raises(ValueError):
        parse_number(bad)


def test_typed_unit_overrides_display_unit():
    assert parse_entry("100 bar", "pressure", Units("us")) == pytest.approx(100e5)
    assert parse_entry("100", "pressure", Units("us")) == pytest.approx(100 * 6894.757)

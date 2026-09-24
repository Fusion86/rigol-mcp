"""MSO5074 regressions; all transport and acquisition data are simulated."""

import io

from PIL import Image
import pytest

from conftest import FakeScope, make_block
from rigol_mcp import drivers, scope as sc

IDN = "RIGOL TECHNOLOGIES,MSO5074,DS5A000000000,00.01.03"
PRE = "2,0,4,1,0.001,-0.002,1,0.5,2,128"


def instrument(payload=b"\x80\x81\x82\x83", **responses):
    return FakeScope(responses={
        "*IDN?": IDN, "*OPC?": "1", ":CHAN1:DISP?": "1",
        ":CHAN1:SCAL?": "1", ":CHAN1:OFFS?": "0",
        ":SYSTem:ERRor?": "0",
        ":WAV:PRE?": PRE, **responses,
    }, read_buffer=make_block(payload))


def test_driver_identity_and_measurements():
    s = instrument(**{":CHAN2:DISP?": "1", ":MEASure:ITEM?": "1e-6"})
    assert drivers.driver_for(IDN) is drivers.MSO5000
    assert sc.measure_between(s, "CHAN1", "CHAN2", "RDELAY") == "1e-6"
    assert ":MEASure:ITEM RRDELAY,CHAN1,CHAN2" in s.written
    assert sc.measure(s, "CHAN1", "VPP") == "1e-6"
    assert ":MEASure:ITEM VPP,CHAN1" in s.written


def test_mso_screen_waveform_uses_ieee_block():
    s = instrument(**{":WAV:DATA?": make_block(b"1,2,3,4").decode("ascii")})
    data = sc.get_waveform(s, "CHAN1")
    assert data["voltages_v"] == [1, 2, 3, 4]
    assert ":WAV:POIN 1000" in s.written
    assert ":WAV:STOP 1000" in s.written


def test_screenshot_converts_bmp_to_png():
    buffer = io.BytesIO()
    Image.new("RGB", (2, 2), (10, 20, 30)).save(buffer, format="BMP")
    s = instrument(buffer.getvalue())
    result = sc.screenshot_png(s)
    assert result.startswith(b"\x89PNG\r\n\x1a\n")
    with Image.open(io.BytesIO(result)) as image:
        assert image.getpixel((0, 0)) == (10, 20, 30)
    assert s.written == [":DISPlay:DATA?"]


@pytest.mark.parametrize("mode,prefix", [("MANUAL", ":CURSor:MANual"), ("TRACK", ":CURSor:TRACk")])
def test_cursor_grid(mode, prefix):
    s = instrument(**{":TIM:SCAL?": "0.001", ":TIM:OFFS?": "0.002",
                      f"{prefix}:CAX?": "500", f"{prefix}:CBX?": "600"})
    sc.set_cursor_positions(s, mode, ax=0.002, bx=0.003)
    assert f"{prefix}:CAX 500" in s.written
    assert f"{prefix}:CBX 600" in s.written
    assert drivers.MSO5000.read_cursor_axes_s(s, prefix) == pytest.approx((0.002, 0.003))



def test_mso_waveform_rejects_incomplete_acquisition():
    s = instrument(**{":WAV:DATA?": "#9000014000+1.000000E+00,"})
    with pytest.raises(ValueError, match="Acquire a fresh waveform"):
        sc.get_waveform(s, "CHAN1")


def test_mso_waveform_accepts_unframed_ascii():
    s = instrument(**{":WAV:DATA?": "1,2,3,4"})
    assert sc.get_waveform(s, "CHAN1")["voltages_v"] == [1, 2, 3, 4]

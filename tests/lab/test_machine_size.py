"""FactorioLab's ``machine.size`` feeds ``adjustCosts``; DSP declares none.

``adjustCosts`` multiplies a crafting machine's cost by ``size[0] * size[1]``
only when the dataset declares a size.  The rate solver mirrors that through
``Machine.size``, so the field must parse faithfully -- and the reason it is
inert for DSP (every machine costs exactly ``costs.machine``) must stay
observable: no DSP machine declares one.
"""

from __future__ import annotations

import pytest

from flab2bp.lab.data import load_vendored
from flab2bp.lab.schema import Machine, _RawMachine


def test_size_is_parsed_as_a_width_height_pair() -> None:
    assert Machine.parse(_RawMachine.model_validate({"size": [3, 4]})).size == (3, 4)
    assert Machine.parse(_RawMachine.model_validate({})).size is None


def test_a_malformed_size_is_refused() -> None:
    with pytest.raises(ValueError, match="width, height"):
        Machine.parse(_RawMachine.model_validate({"size": [3]}))


def test_no_dsp_machine_declares_a_size() -> None:
    data = load_vendored()
    machines = [item.machine for item in data.iter_items() if item.machine is not None]
    assert len(machines) == 52
    assert all(machine.size is None for machine in machines)

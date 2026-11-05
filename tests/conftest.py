import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["FLUIDWORX_CONFIG_DIR"] = tempfile.mkdtemp(prefix="fluidworx-test-")

from fluidworx import circuit, engine  # noqa: E402

EXAMPLES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fluidworx", "examples")


def load(name):
    path = name if os.path.isabs(name) else os.path.join(EXAMPLES, name)
    project, warnings = circuit.load_project(path)
    return circuit.build(project, warnings)


def run_example(name):
    c = load(name)
    return c, engine.Simulator(c)


def by_tag(sim, tag):
    return next(b for b in sim.parts.values() if b.part.tag == tag)


@pytest.fixture
def examples_dir():
    return EXAMPLES

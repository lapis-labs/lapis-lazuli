"""slop_lint: the slop rules' detectors run over a plan, source tree, render extract, and behavior session.

types.py      the detector interface (Hit, Result, Context, DETECTORS, @detector)
engine.py     rules -> detector results -> findings: severity, waivers, locales, packages, leads, coverage
cli.py        `lapis-design slop lint` and the MCP tool: loads the inputs, runs the engine, writes the report
detectors/    the registered detectors, one module per slice
"""

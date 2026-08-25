"""A browser front end for the same builds the CLI runs.

Three modules, in dependency order:

* :mod:`flab2bp.web.payload` -- turns a :class:`flab2bp.pipeline.Build` into
  JSON.  It is the web twin of ``cli._report``, and deliberately reports the
  same things: the refusals, the flow provenance, the belt ceiling and where it
  came from.
* :mod:`flab2bp.web.jobs` -- a build is seconds to minutes, so it is submitted
  and polled rather than awaited inside a request.
* :mod:`flab2bp.web.server` -- the HTTP surface, on the standard library.

Nothing here is imported by the CLI or the solver, and nothing here is needed
to install ``flab2bp`` -- it adds no dependency the core package does not
already have.
"""

from __future__ import annotations

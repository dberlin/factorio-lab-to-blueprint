"""Coverage of ``EBuildCondition`` -- every way the game can refuse a paste.

``docs/RULE_LEDGER.md`` verifies the rules we already knew about.  Nothing there
can find a rule nobody wrote down, which is how ``PowerTooClose`` reached a real
paste unmodelled.  ``docs/EBUILD_COVERAGE.md`` closes that from the other end --
the enum is the complete list of refusals the game has -- and this package is
what stops the matrix drifting away from it.
"""

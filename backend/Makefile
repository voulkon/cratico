.PHONY: test test-fast test-pg

# Run fast tests suitable for CI
test-fast:
	pytest -m "fast and not requires_postgresql"

# Run basic tests including Django DB tests but not PostgreSQL-specific
test:
	pytest -m "not requires_postgresql"

# Run PostgreSQL-specific tests
test-pg:
	PG_TEST=1 pytest -m "requires_postgresql"

# Run all tests including PostgreSQL ones
test-all:
	pytest -m "fast"  # Run fast tests first
	pytest -m "not fast and not requires_postgresql"  # Then other non-PG tests
	PG_TEST=1 pytest -m "requires_postgresql"  # Finally PG tests if configured

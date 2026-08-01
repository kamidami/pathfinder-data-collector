# Contributor guidance

Keep this repository independent from Pathfinder. Integration is exclusively through the
versioned CSV contracts in `contracts/pathfinder/`. Never access a Pathfinder database,
store personal data, bypass access controls, or add network collection without an explicit task.
Use typed domain boundaries, repositories for persistence, and tests for behavior.


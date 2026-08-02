from pathfinder_collector.enums import ConfidenceLevel


def priority_for(confidence: ConfidenceLevel) -> int:
    return {
        ConfidenceLevel.HIGH: 1,
        ConfidenceLevel.MEDIUM: 2,
        ConfidenceLevel.LOW: 3,
    }[confidence]

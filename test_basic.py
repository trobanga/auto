#!/usr/bin/env python3
"""Basic syntax and import test."""

try:
    from auto.models import ConflictType, ConflictComplexity
    print("Basic model imports successful")
    
    # Test enum creation
    conflict_type = ConflictType.CONTENT
    complexity = ConflictComplexity.MODERATE
    print(f"Enum values: {conflict_type}, {complexity}")
    
except ImportError as e:
    print(f"Import error: {e}")
except Exception as e:
    print(f"Other error: {e}")
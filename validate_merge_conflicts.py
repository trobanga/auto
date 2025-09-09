#!/usr/bin/env python3
"""
Simple validation script for merge conflict handling implementation.
Tests basic imports and model creation without external dependencies.
"""

import sys
from pathlib import Path

# Add auto to path for imports
sys.path.insert(0, str(Path(__file__).parent))

def test_imports():
    """Test that all imports work correctly."""
    try:
        # Test model imports
        from auto.models import (
            ConflictType, ConflictComplexity, ConflictDetail, 
            ConflictResolution, ResolutionSuggestion, GitHubRepository
        )
        print("✓ Model imports successful")

        # Test workflow imports
        from auto.workflows.merge_conflicts import (
            _extract_conflicted_files, _analyze_conflict_markers,
            _calculate_complexity_score, _generate_conflict_summary
        )
        print("✓ Merge conflict workflow imports successful")

        # Test AI integration method exists
        from auto.integrations.ai import ClaudeIntegration
        assert hasattr(ClaudeIntegration, 'analyze_merge_conflicts')
        print("✓ AI integration analyze_merge_conflicts method exists")

        return True
    except Exception as e:
        print(f"✗ Import failed: {e}")
        return False

def test_model_creation():
    """Test basic model creation and validation."""
    try:
        from auto.models import (
            ConflictType, ConflictComplexity, ConflictDetail, 
            ConflictResolution, ResolutionSuggestion, GitHubRepository
        )

        # Test ConflictDetail creation
        conflict = ConflictDetail(
            file_path="src/main.py",
            conflict_type=ConflictType.CONTENT,
            complexity=ConflictComplexity.MODERATE,
            description="Test conflict",
            line_numbers=[1, 2, 3]
        )
        assert conflict.file_path == "src/main.py"
        assert conflict.conflict_type == ConflictType.CONTENT
        print("✓ ConflictDetail model creation successful")

        # Test ResolutionSuggestion creation
        suggestion = ResolutionSuggestion(
            file_path="src/main.py",
            suggested_resolution="Test resolution",
            confidence=0.8,
            rationale="Test rationale",
            manual_steps=["Step 1", "Step 2"]
        )
        assert suggestion.confidence == 0.8
        assert len(suggestion.manual_steps) == 2
        print("✓ ResolutionSuggestion model creation successful")

        # Test ConflictResolution creation
        resolution = ConflictResolution(
            conflicts_detected=[conflict],
            resolution_suggestions=[suggestion],
            manual_steps=["Manual step 1"],
            ai_assistance_available=True,
            estimated_resolution_time=15,
            complexity_score=3.0,
            priority_order=["src/main.py"],
            conflict_summary="1 conflict detected",
            resolution_report="Test report"
        )
        assert len(resolution.conflicts_detected) == 1
        assert resolution.estimated_resolution_time == 15
        print("✓ ConflictResolution model creation successful")

        # Test GitHubRepository creation
        repo = GitHubRepository(owner="test", name="repo")
        assert repo.full_name == "test/repo"
        assert repo.github_url == "https://github.com/test/repo"
        print("✓ GitHubRepository model creation successful")

        return True
    except Exception as e:
        print(f"✗ Model creation failed: {e}")
        return False

def test_utility_functions():
    """Test utility functions work correctly."""
    try:
        from auto.workflows.merge_conflicts import (
            _extract_conflicted_files, _analyze_conflict_markers,
            _calculate_complexity_score, _generate_conflict_summary
        )
        from auto.models import ConflictType, ConflictComplexity, ConflictDetail

        # Test conflict file extraction
        git_output = """UU src/main.py
AA README.md
both modified:   config.py"""
        
        files = _extract_conflicted_files(git_output)
        assert len(files) == 3
        assert "src/main.py" in files
        assert "README.md" in files
        assert "config.py" in files
        print("✓ Conflict file extraction successful")

        # Test conflict marker analysis
        content = """def hello():
<<<<<<< HEAD
    print("Hello from main")
=======
    print("Hello from feature")
>>>>>>> feature
    return True"""
        
        conflict_type, complexity, line_numbers, ours, theirs = _analyze_conflict_markers(content)
        assert conflict_type == ConflictType.CONTENT
        assert len(line_numbers) > 0
        assert ours is not None
        assert theirs is not None
        print("✓ Conflict marker analysis successful")

        # Test complexity calculation
        conflicts = [
            ConflictDetail(
                file_path="file1.py",
                conflict_type=ConflictType.CONTENT,
                complexity=ConflictComplexity.SIMPLE,
                description="Simple conflict",
                line_numbers=[]
            ),
            ConflictDetail(
                file_path="file2.py", 
                conflict_type=ConflictType.CONTENT,
                complexity=ConflictComplexity.COMPLEX,
                description="Complex conflict",
                line_numbers=[]
            )
        ]
        
        score = _calculate_complexity_score(conflicts)
        assert 0.0 <= score <= 10.0
        assert score > 1.0  # Should be higher due to complex conflict
        print("✓ Complexity score calculation successful")

        # Test conflict summary generation
        summary = _generate_conflict_summary(conflicts)
        assert "2 merge conflict(s) detected" in summary
        print("✓ Conflict summary generation successful")

        return True
    except Exception as e:
        print(f"✗ Utility function test failed: {e}")
        return False

def test_enum_values():
    """Test enum values are properly defined."""
    try:
        from auto.models import ConflictType, ConflictComplexity

        # Test ConflictType enum
        assert ConflictType.CONTENT == "content"
        assert ConflictType.RENAME == "rename"
        assert ConflictType.DELETE == "delete"
        assert ConflictType.MODIFY_DELETE == "modify_delete"
        assert ConflictType.ADD_ADD == "add_add"
        assert ConflictType.MODE == "mode"
        print("✓ ConflictType enum values correct")

        # Test ConflictComplexity enum
        assert ConflictComplexity.SIMPLE == "simple"
        assert ConflictComplexity.MODERATE == "moderate"
        assert ConflictComplexity.COMPLEX == "complex"
        assert ConflictComplexity.CRITICAL == "critical"
        print("✓ ConflictComplexity enum values correct")

        return True
    except Exception as e:
        print(f"✗ Enum value test failed: {e}")
        return False

def main():
    """Run all validation tests."""
    print("Running merge conflict handling validation...")
    print("=" * 50)

    tests = [
        ("Import Tests", test_imports),
        ("Model Creation Tests", test_model_creation),
        ("Utility Function Tests", test_utility_functions),
        ("Enum Value Tests", test_enum_values),
    ]

    passed = 0
    total = len(tests)

    for test_name, test_func in tests:
        print(f"\n{test_name}:")
        print("-" * 30)
        if test_func():
            passed += 1
            print(f"✓ {test_name} PASSED")
        else:
            print(f"✗ {test_name} FAILED")

    print("\n" + "=" * 50)
    print(f"Validation Results: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 All validation tests passed!")
        return 0
    else:
        print(f"❌ {total - passed} tests failed")
        return 1

if __name__ == "__main__":
    sys.exit(main())
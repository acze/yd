#!/usr/bin/env python3
"""
Test suite for yd (YAML Diff) tool
"""

import subprocess
import sys
import os
from pathlib import Path

def run_test(name, left_file, right_file, expected_differences=None, should_have_differences=True):
    """Run a single test case."""
    print(f"\n🧪 Running test: {name}")
    print(f"   Comparing: {left_file} vs {right_file}")

    try:
        # Run the diff tool using the yd command (available after pip install -e .)
        result = subprocess.run(
            ["yd", left_file, right_file],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent
        )

        has_differences = result.returncode != 0 or len(result.stdout.strip()) > 0

        if should_have_differences and not has_differences:
            print("   ❌ FAILED: Expected differences but found none")
            return False
        elif not should_have_differences and has_differences:
            print("   ❌ FAILED: Expected no differences but found some")
            return False
        else:
            status = "✅ PASSED" if should_have_differences else "✅ PASSED (no differences as expected)"
            print(f"   {status}")
            if result.stdout.strip():
                print("   Output preview:")
                # Show first few lines of output
                lines = result.stdout.strip().split('\n')[:5]
                for line in lines:
                    print(f"     {line}")
                if len(result.stdout.strip().split('\n')) > 5:
                    print("     ...")
            return True

    except Exception as e:
        print(f"   ❌ FAILED: {e}")
        return False

def run_counts_test(name, left_file, right_file, expected_counts):
    """Run a test that checks the counts output."""
    print(f"\n🧪 Running counts test: {name}")
    print(f"   Comparing: {left_file} vs {right_file}")

    try:
        result = subprocess.run(
            ["yd", "--counts", left_file, right_file],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent
        )

        output = result.stdout.strip()
        print(f"   Output: {output}")

        # Parse the counts
        if "Added:" in output and "Removed:" in output and "Modified:" in output:
            parts = output.split(", ")
            added = int(parts[0].split(": ")[1])
            removed = int(parts[1].split(": ")[1])
            modified = int(parts[2].split(": ")[1])

            actual_counts = (added, removed, modified)
            expected_counts = tuple(expected_counts)

            if actual_counts == expected_counts:
                print("   ✅ PASSED")
                return True
            else:
                print(f"   ❌ FAILED: Expected {expected_counts}, got {actual_counts}")
                return False
        else:
            print("   ❌ FAILED: Could not parse counts output")
            return False

    except Exception as e:
        print(f"   ❌ FAILED: {e}")
        return False

def main():
    """Run all tests."""
    print("🚀 Running yd (YAML Diff) test suite")
    print("=" * 50)

    tests_passed = 0
    total_tests = 0

    # Test basic differences
    total_tests += 1
    if run_test("Basic differences", "basic_old.yaml", "basic_new.yaml"):
        tests_passed += 1

    # Test environment variables
    total_tests += 1
    if run_test("Environment variables", "env_old.yaml", "env_new.yaml"):
        tests_passed += 1

    # Test complex nested structures
    total_tests += 1
    if run_test("Complex nested structures", "complex_old.yaml", "complex_new.yaml"):
        tests_passed += 1

    # Test list sorting (should show no differences)
    total_tests += 1
    if run_test("List sorting (should be identical)", "list_old.yaml", "list_new.yaml", should_have_differences=False):
        tests_passed += 1

    # Test counts for basic differences
    total_tests += 1
    if run_counts_test("Basic differences counts", "basic_old.yaml", "basic_new.yaml", [2, 0, 2]):  # 2 added, 0 removed, 2 modified
        tests_passed += 1

    # Test counts for env differences
    total_tests += 1
    if run_counts_test("Environment variables counts", "env_old.yaml", "env_new.yaml", [3, 2, 15]):  # 3 added, 2 removed, 15 modified
        tests_passed += 1

    print("\n" + "=" * 50)
    print(f"📊 Test Results: {tests_passed}/{total_tests} tests passed")

    if tests_passed == total_tests:
        print("🎉 All tests passed!")
        return 0
    else:
        print("💥 Some tests failed!")
        return 1

if __name__ == "__main__":
    sys.exit(main())

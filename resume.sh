#!/bin/bash

OUTPUT_FILE="RESUME_OUTPUT.txt"

{
echo "========================================"
echo "LEGAL AI PROJECT RESUME"
echo "Generated: $(date)"
echo "========================================"
echo

cat PROJECT_STATE.md
echo
echo "========================================"
echo

cat ARCHITECTURE.md
echo
echo "========================================"
echo

cat DECISIONS.md
echo
echo "========================================"
echo

cat attorney_knowledge/ROADMAP.md
echo
echo "========================================"
echo

echo "GIT STATUS"
git status
echo
echo "========================================"
echo

echo "GIT BRANCHES"
git branch
echo

echo "========================================"
echo

echo "LAST 10 COMMITS"
git log --oneline -10
echo

} | tee "$OUTPUT_FILE"

echo
echo "Saved to: $OUTPUT_FILE"

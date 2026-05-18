"""
kroniqo-agent/tools/code_runner.py
Gives Kroniqo the ability to RUN code and verify its own fixes automatically.
Outcome = pass/fail from subprocess. No human needed.
"""

import subprocess
import tempfile
import os
import sys
import re

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'kroniqo-core'))
from consequence_graph import log_decision, record_outcome


# Dangerous patterns — block before running
_BLOCKED_PATTERNS = [
    "os.system", "os.remove", "os.rmdir", "shutil.rmtree",
    "subprocess.call", "subprocess.Popen", "__import__('os').system",
    "open('/etc", "open('/root", "open('/sys",
    "rm -rf", "format(", ":(){:|:&};:",  # fork bomb
]

def _is_safe(code: str) -> tuple[bool, str]:
    """Basic static check before running code."""
    for pattern in _BLOCKED_PATTERNS:
        if pattern in code:
            return False, f"Blocked pattern detected: {pattern}"
    return True, ""


def run_python(code: str, timeout: int = 10, sandbox: bool = True) -> dict:
    """
    Run Python code string in subprocess.
    sandbox=True blocks dangerous patterns before execution.
    Returns result dict.
    """
    if sandbox:
        safe, reason = _is_safe(code)
        if not safe:
            return {
                "success": False,
                "stdout": "",
                "stderr": f"[Sandbox] Blocked: {reason}",
                "returncode": -2,
            }

    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
        f.write(code)
        tmp_path = f.name
    try:
        result = subprocess.run(
            [sys.executable, tmp_path],
            capture_output=True, text=True, timeout=timeout,
            # Restrict environment — no access to secrets
            env={
                "PATH": os.environ.get("PATH", ""),
                "PYTHONPATH": os.environ.get("PYTHONPATH", ""),
                "HOME": os.environ.get("HOME", ""),
            }
        )
        return {
            "success":    result.returncode == 0,
            "stdout":     result.stdout.strip(),
            "stderr":     result.stderr.strip(),
            "returncode": result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "stdout": "", "stderr": f"Sandbox: Timeout after {timeout}s", "returncode": -1}
    finally:
        try: os.unlink(tmp_path)
        except: pass


def extract_code_block(text: str) -> str:
    """Pull code from markdown fences if present."""
    match = re.search(r"```(?:python)?\n(.*?)```", text, re.DOTALL)
    return match.group(1).strip() if match else text.strip()


def debug_task(broken_code: str, ask_fn, backend: str = "groq") -> dict:
    """
    Full automatic debug loop:
    1. Run broken code → confirm it fails
    2. Ask Kroniqo to fix it
    3. Run the fix → pass/fail
    4. Record outcome to consequence graph automatically
    """
    print("\n[Code Runner] Testing original code...")
    original = run_python(broken_code)

    if original["success"]:
        print("[Code Runner] Code already works.")
        return {"status": "already_works", "result": original}

    print(f"[Code Runner] Broken. Error: {original['stderr'][:150]}")
    print("[Code Runner] Asking Kroniqo to fix...\n")

    task = f"""This Python code has a bug. Fix it and return ONLY the corrected code in a Python code block.

BROKEN CODE:
```python
{broken_code}
```

ERROR:
{original['stderr']}

Return the complete fixed code in a code block. Then on the last line: CONFIDENCE: X.X"""

    answer, confidence, decision_id = ask_fn("code_debug", task, backend)
    fixed_code = extract_code_block(answer)

    print("[Code Runner] Running Kroniqo's fix...")
    fix_result = run_python(fixed_code)

    if fix_result["success"]:
        print(f"[Code Runner] Fix worked. Output: {fix_result['stdout'][:100]}")
        record_outcome(decision_id, "correct", "medium",
                       f"Fix ran successfully. Output: {fix_result['stdout'][:80]}")
        status = "correct"
    else:
        print(f"[Code Runner] Fix failed. Error: {fix_result['stderr'][:100]}")
        record_outcome(decision_id, "wrong", "medium",
                       f"Fix still broken: {fix_result['stderr'][:80]}")
        status = "wrong"

    return {
        "status":      status,
        "fixed_code":  fixed_code,
        "result":      fix_result,
        "decision_id": decision_id,
    }


def debug_folder(folder_path: str, ask_fn, backend: str = "groq"):
    """
    Batch debug — give Kroniqo a folder of broken .py files.
    Each file is a decision. Kroniqo ages automatically across the batch.
    """
    folder   = os.path.abspath(folder_path)
    py_files = sorted(f for f in os.listdir(folder) if f.endswith('.py') and not f.endswith('_fixed.py'))

    if not py_files:
        print(f"No .py files in {folder}")
        return

    print(f"\n[Batch Debug] {len(py_files)} files found in {folder}")
    results = {}

    for fname in py_files:
        fpath = os.path.join(folder, fname)
        print(f"\n{'─'*50}")
        print(f"File: {fname}")
        with open(fpath) as f:
            code = f.read()

        result = debug_task(code, ask_fn, backend)
        results[fname] = result

        if result["status"] == "correct":
            fixed_path = fpath.replace('.py', '_fixed.py')
            with open(fixed_path, 'w') as f:
                f.write(result["fixed_code"])
            print(f"Saved: {os.path.basename(fixed_path)}")

    correct = sum(1 for r in results.values() if r["status"] == "correct")
    print(f"\n{'='*50}")
    print(f"Batch done. {correct}/{len(py_files)} fixed. Kroniqo aged {len(py_files)} decisions.")
    return results

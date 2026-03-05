"""Tests de seguridad para verificar separación UI/Core.

Verifica que la UI NO calcula políticas de retry ni modifica campos de negocio.
"""

import ast
import inspect
from pathlib import Path


def test_ui_does_not_calculate_retry():
    """Verifica que interface.py NO calcula next_retry_at (sin random.uniform)."""
    interface_path = Path(__file__).parent.parent / "vat_validator" / "ui" / "interface.py"
    source = interface_path.read_text(encoding="utf-8")
    
    # Parsear AST
    tree = ast.parse(source)
    
    # Buscar _apply_result
    apply_result_func = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_apply_result":
            apply_result_func = node
            break
    
    assert apply_result_func is not None, "_apply_result() debe existir"
    
    # Verificar que NO usa random.uniform ni timedelta para cálculos
    func_source = ast.get_source_segment(source, apply_result_func)
    
    # No debe calcular jitter
    assert "random.uniform" not in func_source, (
        "_apply_result() NO debe calcular jitter con random.uniform(). "
        "Eso es responsabilidad de RetryPolicy."
    )
    
    # No debe calcular next_retry_at
    assert "info.next_retry_at = now +" not in func_source, (
        "_apply_result() NO debe asignar next_retry_at. "
        "Eso es responsabilidad de RetryPolicy."
    )
    
    assert "info.next_retry_at = datetime" not in func_source, (
        "_apply_result() NO debe asignar next_retry_at. "
        "Eso es responsabilidad de RetryPolicy."
    )
    
    # No debe modificar info.status (solo leerlo)
    # Permitimos leer info.status pero no asignar
    status_assignments = func_source.count("info.status = ")
    assert status_assignments == 0, (
        f"_apply_result() NO debe asignar info.status ({status_assignments} asignaciones encontradas). "
        "El core ya lo actualizó en retry_logic.py."
    )


def test_ui_does_not_modify_counters():
    """Verifica que interface.py NO incrementa contadores (throttles, attempts_hard)."""
    interface_path = Path(__file__).parent.parent / "vat_validator" / "ui" / "interface.py"
    source = interface_path.read_text(encoding="utf-8")
    
    tree = ast.parse(source)
    
    apply_result_func = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_apply_result":
            apply_result_func = node
            break
    
    assert apply_result_func is not None
    
    func_source = ast.get_source_segment(source, apply_result_func)
    
    # No debe incrementar throttles
    assert "info.throttles +=" not in func_source, (
        "_apply_result() NO debe incrementar info.throttles. "
        "Eso lo hace retry_logic.py."
    )
    
    # No debe incrementar attempts_hard
    assert "info.attempts_hard +=" not in func_source, (
        "_apply_result() NO debe incrementar info.attempts_hard. "
        "Eso lo hace retry_logic.py."
    )
    
    # No debe incrementar auto_retry_count
    assert "info.auto_retry_count +=" not in func_source, (
        "_apply_result() NO debe incrementar info.auto_retry_count. "
        "Eso lo hace RetryPolicy."
    )


def test_ui_does_not_import_random_for_retry():
    """Verifica que interface.py NO importa random (no necesita calcular jitter)."""
    interface_path = Path(__file__).parent.parent / "vat_validator" / "ui" / "interface.py"
    source = interface_path.read_text(encoding="utf-8")
    
    tree = ast.parse(source)
    
    # Buscar imports de random
    random_imported = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "random":
                    random_imported = True
        elif isinstance(node, ast.ImportFrom):
            if node.module == "random":
                random_imported = True
    
    assert not random_imported, (
        "interface.py NO debe importar random. "
        "Los cálculos de jitter son responsabilidad de RetryPolicy."
    )


def test_retry_policy_is_single_source_of_truth():
    """Verifica que RetryPolicy calcula next_retry_at."""
    from vat_validator.retry_policy import RetryPolicy
    
    # Verificar que el método existe
    assert hasattr(RetryPolicy, "apply_retry_decision"), (
        "RetryPolicy debe tener método apply_retry_decision()"
    )
    
    # Verificar firma
    import inspect
    sig = inspect.signature(RetryPolicy.apply_retry_decision)
    assert "vat_info" in sig.parameters, (
        "apply_retry_decision() debe recibir vat_info"
    )


def test_retry_logic_uses_retry_policy():
    """Verifica que retry_logic.py usa RetryPolicy."""
    retry_logic_path = Path(__file__).parent.parent / "vat_validator" / "retry_logic.py"
    source = retry_logic_path.read_text(encoding="utf-8")
    
    # Debe importar RetryPolicy
    assert "from .retry_policy import RetryPolicy" in source, (
        "retry_logic.py debe importar RetryPolicy"
    )
    
    # Debe instanciar RetryPolicy
    assert "self.retry_policy = RetryPolicy(" in source, (
        "retry_logic.py debe instanciar RetryPolicy"
    )
    
    # Debe llamar apply_retry_decision
    assert "self.retry_policy.apply_retry_decision(info)" in source, (
        "retry_logic.py debe llamar apply_retry_decision()"
    )


def test_core_updates_fields_before_ui():
    """Verifica que retry_logic.py actualiza campos ANTES de notificar UI."""
    retry_logic_path = Path(__file__).parent.parent / "vat_validator" / "retry_logic.py"
    source = retry_logic_path.read_text(encoding="utf-8")
    
    # Debe actualizar info.status antes de callback
    assert "info.status = status" in source, (
        "retry_logic.py debe actualizar info.status"
    )
    
    # Debe actualizar throttles para THROTTLED
    assert "info.throttles += 1" in source, (
        "retry_logic.py debe incrementar info.throttles para THROTTLED"
    )
    
    # Debe actualizar attempts_hard para TIMEOUT/ERROR
    assert "info.attempts_hard += 1" in source, (
        "retry_logic.py debe incrementar info.attempts_hard para TIMEOUT/ERROR"
    )
    
    # Debe pasar prev_status para undo
    assert 'result["_prev_status"]' in source or "result['_prev_status']" in source, (
        "retry_logic.py debe pasar _prev_status a UI para undo stack"
    )

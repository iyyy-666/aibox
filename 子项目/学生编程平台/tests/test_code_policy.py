from aibox_studio.policy import CodePolicy


def test_policy_allows_declared_aibox_capability():
    policy = CodePolicy(
        allowed_imports=("aibox",),
        capabilities=("arm.open",),
    )

    result = policy.validate("from aibox import Arm\narm = Arm()\narm.open()\n")

    assert result.allowed is True
    assert result.diagnostics == ()


def test_policy_rejects_undeclared_import_with_line_number():
    policy = CodePolicy(allowed_imports=("aibox",), capabilities=())

    result = policy.validate("import os\nprint('x')\n")

    assert result.allowed is False
    assert result.diagnostics[0].line == 1
    assert result.diagnostics[0].code == "IMPORT_NOT_ALLOWED"


def test_policy_rejects_capability_not_granted_to_experiment():
    policy = CodePolicy(
        allowed_imports=("aibox",),
        capabilities=("arm.open",),
    )

    result = policy.validate("from aibox import Arm\narm = Arm()\narm.servo(1, 1500)\n")

    assert result.allowed is False
    assert result.diagnostics[0].line == 3
    assert result.diagnostics[0].code == "CAPABILITY_NOT_ALLOWED"


def test_policy_rejects_dangerous_builtin():
    policy = CodePolicy(allowed_imports=("aibox",), capabilities=())

    result = policy.validate("open('/etc/shadow').read()\n")

    assert result.allowed is False
    assert result.diagnostics[0].code == "BUILTIN_NOT_ALLOWED"


def test_policy_checks_aibox_capability_through_import_alias():
    policy = CodePolicy(
        allowed_imports=("aibox",),
        capabilities=("arm.open",),
    )

    result = policy.validate("from aibox import Arm as Robot\nRobot().servo(1, 1500)\n")

    assert result.allowed is False
    assert result.diagnostics[0].code == "CAPABILITY_NOT_ALLOWED"


def test_policy_rejects_dynamic_import_builtin():
    policy = CodePolicy(allowed_imports=("aibox",), capabilities=())

    result = policy.validate("__import__('os').getcwd()\n")

    assert result.allowed is False
    assert result.diagnostics[0].code == "BUILTIN_NOT_ALLOWED"


def test_policy_rejects_wildcard_import():
    policy = CodePolicy(allowed_imports=("aibox",), capabilities=())

    result = policy.validate("from aibox import *\n")

    assert result.allowed is False
    assert result.diagnostics[0].code == "IMPORT_NOT_ALLOWED"


def test_policy_rejects_dangerous_builtin_stored_in_variable():
    policy = CodePolicy(allowed_imports=("aibox",), capabilities=())

    result = policy.validate("reader = open\nreader('/etc/shadow')\n")

    assert result.allowed is False
    assert result.diagnostics[0].code == "BUILTIN_NOT_ALLOWED"


def test_policy_tracks_aibox_class_stored_in_variable():
    policy = CodePolicy(allowed_imports=("aibox",), capabilities=("arm.open",))

    result = policy.validate("from aibox import Arm\nfactory = Arm\nfactory().servo(1, 1500)\n")

    assert result.allowed is False
    assert result.diagnostics[0].code == "CAPABILITY_NOT_ALLOWED"


def test_policy_tracks_class_accessed_through_aibox_module():
    policy = CodePolicy(allowed_imports=("aibox",), capabilities=("arm.open",))

    result = policy.validate("import aibox\nfactory = aibox.Arm\nfactory().servo(1, 1500)\n")

    assert result.allowed is False
    assert result.diagnostics[0].code == "CAPABILITY_NOT_ALLOWED"


def test_policy_rejects_builtins_namespace_access():
    policy = CodePolicy(allowed_imports=("aibox",), capabilities=())

    result = policy.validate("builtins = __builtins__\nreader = builtins.open\n")

    assert result.allowed is False
    assert result.diagnostics[0].code == "BUILTIN_NOT_ALLOWED"


"""
Operator modules for BlenderToRCP.
"""

_needs_reload = "bpy" in locals()

import bpy

from . import export_operator
from . import bake_export_operator
from . import nodegroup_operators
from . import validation_operators
from . import variant_operators
from . import geometry_variant_operators

if _needs_reload:
    import importlib
    export_operator = importlib.reload(export_operator)
    bake_export_operator = importlib.reload(bake_export_operator)
    nodegroup_operators = importlib.reload(nodegroup_operators)
    validation_operators = importlib.reload(validation_operators)
    variant_operators = importlib.reload(variant_operators)
    geometry_variant_operators = importlib.reload(geometry_variant_operators)


def register():
    """Register all operator classes."""
    export_operator.register()
    bake_export_operator.register()
    nodegroup_operators.register()
    validation_operators.register()
    variant_operators.register()
    geometry_variant_operators.register()


def unregister():
    """Unregister all operator classes."""
    geometry_variant_operators.unregister()
    variant_operators.unregister()
    validation_operators.unregister()
    nodegroup_operators.unregister()
    bake_export_operator.unregister()
    export_operator.unregister()

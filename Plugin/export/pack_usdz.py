"""
USDZ packager

Creates USDZ files as stored (uncompressed) ZIP archives.
"""

import os
import zipfile
from pathlib import Path
from typing import Optional, List

from .. import prefs as addon_prefs

def create_usdz(usd_path: str, output_path: str, settings, context, diagnostics=None):
    """Create USDZ file from USD stage
    
    Args:
        usd_path: Path to USD file
        output_path: Path to output USDZ file
        settings: Export settings
        context: Blender context
        diagnostics: ExportDiagnostics instance
    """
    # Check for external usdzip tool first
    import bpy
    prefs = addon_prefs.get_preferences(context)
    usdzip_path = prefs.usdzip_path if prefs and hasattr(prefs, 'usdzip_path') else None
    
    if usdzip_path and os.path.exists(usdzip_path):
        # Use external tool
        create_usdz_with_tool(usd_path, output_path, usdzip_path)
    else:
        # Use Python fallback
        create_usdz_python(usd_path, output_path, settings, diagnostics)


def create_usdz_with_tool(usd_path: str, output_path: str, usdzip_path: str):
    """Create USDZ using external usdzip tool"""
    import subprocess
    
    try:
        result = subprocess.run(
            [usdzip_path, output_path, usd_path],
            capture_output=True,
            text=True,
            check=True
        )
        print(f"USDZ created using usdzip: {output_path}")
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"usdzip failed: {e.stderr}") from e
    except Exception as e:
        raise RuntimeError(f"Failed to run usdzip: {e}") from e


def create_usdz_python(usd_path: str, output_path: str, settings, diagnostics=None):
    """Create USDZ using Python ZIP (stored, uncompressed)"""
    usd_file = Path(usd_path)
    usd_dir = usd_file.parent
    
    # Ensure output directory exists
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    
    # Create ZIP archive with no compression (stored)
    with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_STORED) as usdz:
        # Add main USD file at root
        usd_arcname = usd_file.name
        usdz.write(usd_path, usd_arcname)
        
        # Add materials directory if it exists
        materials_dir = usd_dir / "materials"
        if materials_dir.exists():
            for mat_file in materials_dir.rglob("*"):
                if mat_file.is_file():
                    arcname = mat_file.relative_to(usd_dir)
                    usdz.write(str(mat_file), str(arcname))

        # Add textures directory if it exists
        textures_dir = usd_dir / "textures"
        if textures_dir.exists():
            for texture_file in textures_dir.rglob("*"):
                if texture_file.is_file():
                    # Preserve relative path structure
                    arcname = texture_file.relative_to(usd_dir)
                    usdz.write(str(texture_file), str(arcname))
        
        # Add material_sets.json if it exists
        mat_sets_json = usd_dir / "material_sets.json"
        if mat_sets_json.exists():
            usdz.write(str(mat_sets_json), mat_sets_json.name)
    
    print(f"USDZ created: {output_path}")
    
    if diagnostics:
        diagnostics.add_warning("USDZ packaged using Python fallback (stored ZIP)")


def validate_usdz(usdz_path: str) -> bool:
    """Validate USDZ file structure
    
    Args:
        usdz_path: Path to USDZ file
        
    Returns:
        True if valid, False otherwise
    """
    try:
        with zipfile.ZipFile(usdz_path, 'r') as usdz:
            # Check for at least one USD file at root
            root_files = [f for f in usdz.namelist() if '/' not in f or f.count('/') == 1]
            usd_files = [f for f in root_files if f.endswith(('.usd', '.usda', '.usdc'))]
            
            if not usd_files:
                return False
            
            # Check that main USD file is readable
            main_usd = usd_files[0]
            try:
                usdz.read(main_usd)
            except Exception:
                return False
            
            return True
    except Exception:
        return False

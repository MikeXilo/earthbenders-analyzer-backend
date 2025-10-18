#!/usr/bin/env python3
"""
Validation script to check refactoring completeness
Validates that all critical issues have been resolved
"""

import os
import sys
import re
from pathlib import Path

def check_file_consistency():
    """Check that all files use consistent naming"""
    issues = []
    
    # Files to check for dem_path usage
    files_to_check = [
        'services/database.py',
        'routes/lidar.py', 
        'routes/usgs_dem.py',
        'routes/polygon.py',
        'services/analysis_statistics.py'
    ]
    
    print("🔍 Checking file consistency...")
    
    for file_path in files_to_check:
        if not os.path.exists(file_path):
            issues.append(f"❌ File not found: {file_path}")
            continue
            
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
            
        # Check for old srtm_path references
        srtm_path_matches = re.findall(r'srtm_path', content)
        if srtm_path_matches:
            issues.append(f"❌ {file_path}: Found {len(srtm_path_matches)} 'srtm_path' references")
            
        # Check for dem_path usage (should be present)
        dem_path_matches = re.findall(r'dem_path', content)
        if not dem_path_matches:
            issues.append(f"⚠️  {file_path}: No 'dem_path' references found")
        else:
            print(f"✅ {file_path}: {len(dem_path_matches)} 'dem_path' references")
    
    return issues

def check_import_consistency():
    """Check that imports are consistent"""
    issues = []
    
    print("\n🔍 Checking import consistency...")
    
    # Check route files use new imports
    route_files = ['routes/lidar.py', 'routes/usgs_dem.py', 'routes/polygon.py']
    
    for file_path in route_files:
        if not os.path.exists(file_path):
            continue
            
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
            
        # Should import from dem_processor, not srtm
        if 'from services.srtm import process_srtm_files' in content:
            issues.append(f"❌ {file_path}: Still importing from services.srtm")
        elif 'from services.dem_processor import process_dem_files' in content:
            print(f"✅ {file_path}: Correct import from dem_processor")
        else:
            issues.append(f"⚠️  {file_path}: No clear import pattern found")
    
    return issues

def check_function_calls():
    """Check that function calls are updated"""
    issues = []
    
    print("\n🔍 Checking function calls...")
    
    # Check route files use new function names
    route_files = ['routes/lidar.py', 'routes/usgs_dem.py', 'routes/polygon.py']
    
    for file_path in route_files:
        if not os.path.exists(file_path):
            continue
            
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
            
        # Should call process_dem_files, not process_srtm_files
        if 'process_srtm_files(' in content:
            issues.append(f"❌ {file_path}: Still calling process_srtm_files")
        elif 'process_dem_files(' in content:
            print(f"✅ {file_path}: Correct function call process_dem_files")
        else:
            issues.append(f"⚠️  {file_path}: No clear function call pattern found")
    
    return issues

def check_database_schema():
    """Check database schema consistency"""
    issues = []
    
    print("\n🔍 Checking database schema...")
    
    # Check create_tables.py
    if os.path.exists('create_tables.py'):
        with open('create_tables.py', 'r', encoding='utf-8') as f:
            content = f.read()
            
        if 'srtm_path' in content:
            issues.append("❌ create_tables.py: Still references 'srtm_path'")
        elif 'dem_path' in content:
            print("✅ create_tables.py: Uses 'dem_path'")
        else:
            issues.append("⚠️  create_tables.py: No clear schema pattern found")
    
    # Check migration script exists
    if not os.path.exists('migrate_dem_schema.py'):
        issues.append("❌ Migration script not found: migrate_dem_schema.py")
    else:
        print("✅ Migration script exists: migrate_dem_schema.py")
    
    return issues

def check_error_messages():
    """Check that error messages are updated"""
    issues = []
    
    print("\n🔍 Checking error messages...")
    
    files_to_check = [
        'services/database.py',
        'services/analysis_statistics.py'
    ]
    
    for file_path in files_to_check:
        if not os.path.exists(file_path):
            continue
            
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
            
        # Check for old SRTM error messages
        srtm_error_matches = re.findall(r'SRTM file not found', content)
        if srtm_error_matches:
            issues.append(f"❌ {file_path}: Still has 'SRTM file not found' messages")
        elif 'DEM file not found' in content:
            print(f"✅ {file_path}: Uses 'DEM file not found' messages")
    
    return issues

def check_new_files():
    """Check that new files exist"""
    issues = []
    
    print("\n🔍 Checking new files...")
    
    required_files = [
        'services/dem_processor.py',
        'config/dem_sources.py',
        'migrate_dem_schema.py',
        'tests/test_refactoring.py',
        'DEPLOYMENT_CHECKLIST.md'
    ]
    
    for file_path in required_files:
        if os.path.exists(file_path):
            print(f"✅ {file_path}: Exists")
        else:
            issues.append(f"❌ {file_path}: Missing")
    
    return issues

def check_legacy_compatibility():
    """Check that legacy compatibility is maintained"""
    issues = []
    
    print("\n🔍 Checking legacy compatibility...")
    
    if os.path.exists('services/dem_processor.py'):
        with open('services/dem_processor.py', 'r', encoding='utf-8') as f:
            content = f.read()
            
        if 'def process_srtm_files(' in content:
            print("✅ Legacy function process_srtm_files() maintained")
        else:
            issues.append("❌ Legacy function process_srtm_files() not found")
    
    return issues

def main():
    """Run all validation checks"""
    print("🚀 Starting refactoring validation...")
    print("=" * 60)
    
    all_issues = []
    
    # Run all checks
    all_issues.extend(check_file_consistency())
    all_issues.extend(check_import_consistency())
    all_issues.extend(check_function_calls())
    all_issues.extend(check_database_schema())
    all_issues.extend(check_error_messages())
    all_issues.extend(check_new_files())
    all_issues.extend(check_legacy_compatibility())
    
    print("\n" + "=" * 60)
    print("📊 VALIDATION RESULTS")
    print("=" * 60)
    
    if not all_issues:
        print("🎉 ALL CHECKS PASSED!")
        print("✅ Refactoring is complete and consistent")
        print("✅ All critical issues have been resolved")
        print("✅ System is ready for deployment")
        return 0
    else:
        print(f"❌ FOUND {len(all_issues)} ISSUES:")
        for issue in all_issues:
            print(f"  {issue}")
        print("\n🔧 Please fix these issues before deployment")
        return 1

if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)

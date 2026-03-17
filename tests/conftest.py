"""Pytest configuration and fixtures"""

import pytest
import tempfile
import shutil
import os
from pathlib import Path

# Add src to path
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))


@pytest.fixture
def temp_project_dir():
    """Create temporary project directory for testing"""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir)


@pytest.fixture
def sample_python_file(temp_project_dir):
    """Create a sample Python file"""
    content = '''
import os
import sys
from pathlib import Path

class MyClass:
    """Example class"""
    
    def __init__(self):
        pass
    
    def method(self):
        pass

if __name__ == "__main__":
    obj = MyClass()
    obj.method()
'''
    
    file_path = os.path.join(temp_project_dir, 'example.py')
    with open(file_path, 'w') as f:
        f.write(content)
    
    return file_path


@pytest.fixture
def sample_cpp_file(temp_project_dir):
    """Create a sample C++ file"""
    content = '''
#include <iostream>
#include <vector>

class MyClass {
public:
    void doSomething() {
        std::cout << "Hello" << std::endl;
    }
};

int main() {
    MyClass obj;
    obj.doSomething();
    return 0;
}
'''
    
    file_path = os.path.join(temp_project_dir, 'example.cpp')
    with open(file_path, 'w') as f:
        f.write(content)
    
    return file_path


@pytest.fixture
def temp_memory_dir():
    """Create temporary memory directory"""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir)

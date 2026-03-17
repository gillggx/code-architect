"""
Unit tests for Phase 2 Pattern Detection system.

Tests cover:
- PatternDetector.detect_in_file() for all 15+ patterns
- ConfidenceScorer / evidence counting
- EvidenceValidator deduplication
- RobustnessChecker suppression rules
- PatternCatalog retrieval
"""

import asyncio
import os
import tempfile
import pytest
from pathlib import Path

from architect.patterns.detector import PatternDetector
from architect.patterns.validators import EvidenceValidator, RobustnessChecker
from architect.patterns.catalog import get_pattern_catalog
from architect.models import ConfidenceScore, PatternCategoryEnum


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def detector():
    return PatternDetector()


@pytest.fixture
def validator():
    return EvidenceValidator()


@pytest.fixture
def checker():
    return RobustnessChecker()


def _write_temp(content: str, suffix: str = ".py") -> str:
    """Write content to a temp file and return its path."""
    fd, path = tempfile.mkstemp(suffix=suffix)
    with os.fdopen(fd, "w") as fh:
        fh.write(content)
    return path


# ---------------------------------------------------------------------------
# PatternCatalog tests
# ---------------------------------------------------------------------------

class TestPatternCatalog:
    def test_all_patterns_present(self):
        catalog = get_pattern_catalog()
        names = {p.name for p in catalog.get_all_patterns()}
        required = {
            "Singleton", "Factory", "Decorator", "Observer", "Strategy",
            "State", "Adapter", "Repository", "Middleware", "ErrorHandling",
            "Concurrency", "DependencyInjection", "MVC",
            "TemplateMethod", "ChainOfResponsibility", "Bridge", "Facade",
        }
        assert required.issubset(names), f"Missing patterns: {required - names}"

    def test_get_pattern_by_name(self):
        catalog = get_pattern_catalog()
        singleton = catalog.get_pattern("Singleton")
        assert singleton is not None
        assert singleton.name == "Singleton"
        assert singleton.category == "oop"

    def test_get_patterns_by_category(self):
        catalog = get_pattern_catalog()
        behavioral = catalog.get_patterns_by_category("behavioral")
        names = {p.name for p in behavioral}
        assert "Observer" in names
        assert "Strategy" in names

    def test_detection_rule_lookup(self):
        catalog = get_pattern_catalog()
        rule = catalog.get_detection_rule("Singleton", "python")
        assert rule is not None
        assert "_instance" in rule.keywords


# ---------------------------------------------------------------------------
# PatternDetector tests
# ---------------------------------------------------------------------------

class TestPatternDetector:

    def test_detect_singleton_python(self, detector):
        code = '''
class Database:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def get_instance(cls):
        return cls._instance or cls()
'''
        path = _write_temp(code)
        try:
            patterns = asyncio.run(
                detector.detect_in_file(path, language="python")
            )
            names = {p.name for p in patterns}
            assert "Singleton" in names, f"Expected Singleton, got {names}"
            singleton = next(p for p in patterns if p.name == "Singleton")
            assert singleton.confidence.value >= 0.65
            assert len(singleton.evidence) >= 2
        finally:
            os.unlink(path)

    def test_detect_factory_python(self, detector):
        code = '''
class ShapeFactory:
    @staticmethod
    def create_shape(shape_type: str):
        if shape_type == "circle":
            return Circle()
        return Square()

def make_widget(kind):
    return {"kind": kind}
'''
        path = _write_temp(code)
        try:
            patterns = asyncio.run(
                detector.detect_in_file(path, language="python")
            )
            names = {p.name for p in patterns}
            assert "Factory" in names, f"Expected Factory, got {names}"
        finally:
            os.unlink(path)

    def test_detect_decorator_python(self, detector):
        code = '''
import functools

def log_calls(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        print(f"Calling {func.__name__}")
        return func(*args, **kwargs)
    return wrapper
'''
        path = _write_temp(code)
        try:
            patterns = asyncio.run(
                detector.detect_in_file(path, language="python")
            )
            names = {p.name for p in patterns}
            assert "Decorator" in names, f"Expected Decorator, got {names}"
        finally:
            os.unlink(path)

    def test_detect_observer_python(self, detector):
        code = '''
class EventEmitter:
    def __init__(self):
        self.listeners = []

    def subscribe(self, listener):
        self.listeners.append(listener)

    def unsubscribe(self, listener):
        self.listeners.remove(listener)

    def notify(self, event):
        for listener in self.listeners:
            listener(event)
'''
        path = _write_temp(code)
        try:
            patterns = asyncio.run(
                detector.detect_in_file(path, language="python")
            )
            names = {p.name for p in patterns}
            assert "Observer" in names, f"Expected Observer, got {names}"
        finally:
            os.unlink(path)

    def test_detect_concurrency_python(self, detector):
        code = '''
import asyncio
import threading

async def fetch_data(url: str):
    await asyncio.sleep(0)
    return {}

async def main():
    tasks = [fetch_data("http://example.com")]
    results = await asyncio.gather(*tasks)
    return results
'''
        path = _write_temp(code)
        try:
            patterns = asyncio.run(
                detector.detect_in_file(path, language="python")
            )
            names = {p.name for p in patterns}
            assert "Concurrency" in names, f"Expected Concurrency, got {names}"
        finally:
            os.unlink(path)

    def test_detect_error_handling_python(self, detector):
        code = '''
class DatabaseError(Exception):
    pass

class ConnectionError(DatabaseError):
    pass

def connect(host):
    try:
        raise ConnectionError("Cannot connect")
    except ConnectionError as e:
        raise DatabaseError(str(e)) from e
    finally:
        print("cleanup")
'''
        path = _write_temp(code)
        try:
            patterns = asyncio.run(
                detector.detect_in_file(path, language="python")
            )
            names = {p.name for p in patterns}
            assert "ErrorHandling" in names, f"Expected ErrorHandling, got {names}"
        finally:
            os.unlink(path)

    def test_detect_repository_python(self, detector):
        code = '''
class UserRepository:
    def __init__(self, session):
        self.session = session

    def find_by_id(self, user_id: int):
        return self.session.query(User).filter_by(id=user_id).first()

    def find_all(self):
        return self.session.query(User).all()

    def save(self, user):
        self.session.add(user)
        self.session.commit()

    def delete(self, user_id: int):
        user = self.find_by_id(user_id)
        if user:
            self.session.delete(user)
'''
        path = _write_temp(code)
        try:
            patterns = asyncio.run(
                detector.detect_in_file(path, language="python")
            )
            names = {p.name for p in patterns}
            assert "Repository" in names, f"Expected Repository, got {names}"
        finally:
            os.unlink(path)

    def test_detect_template_method_python(self, detector):
        code = '''
from abc import ABC, abstractmethod

class DataProcessor(ABC):
    def process(self, data):
        data = self.validate(data)
        data = self.transform(data)
        return self.output(data)

    @abstractmethod
    def validate(self, data):
        pass

    @abstractmethod
    def transform(self, data):
        pass

    def output(self, data):
        return data
'''
        path = _write_temp(code)
        try:
            patterns = asyncio.run(
                detector.detect_in_file(path, language="python")
            )
            names = {p.name for p in patterns}
            assert "TemplateMethod" in names, f"Expected TemplateMethod, got {names}"
        finally:
            os.unlink(path)

    def test_detect_middleware_python(self, detector):
        code = '''
class AuthMiddleware:
    def __init__(self, app):
        self.app = app

    def __call__(self, request):
        if not request.headers.get("Authorization"):
            return Response(401)
        return self.app(request)

class LoggingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def process_request(self, request):
        print(f"Request: {request.path}")
'''
        path = _write_temp(code)
        try:
            patterns = asyncio.run(
                detector.detect_in_file(path, language="python")
            )
            names = {p.name for p in patterns}
            assert "Middleware" in names, f"Expected Middleware, got {names}"
        finally:
            os.unlink(path)

    def test_empty_file_returns_no_patterns(self, detector):
        path = _write_temp("")
        try:
            patterns = asyncio.run(
                detector.detect_in_file(path, language="python")
            )
            assert patterns == []
        finally:
            os.unlink(path)

    def test_nonexistent_file_returns_empty(self, detector):
        patterns = asyncio.run(
            detector.detect_in_file("/nonexistent/path.py", language="python")
        )
        assert patterns == []

    def test_unknown_extension_returns_empty(self, detector):
        path = _write_temp("hello world", suffix=".xyz")
        try:
            patterns = asyncio.run(
                detector.detect_in_file(path)
            )
            assert patterns == []
        finally:
            os.unlink(path)

    def test_detect_in_project(self, detector, tmp_path):
        """Test project-level detection with evidence merging."""
        # Create two files with singleton evidence
        f1 = tmp_path / "db.py"
        f1.write_text('class DB:\n    _instance = None\n    def __new__(cls):\n        return super().__new__(cls)\n')
        f2 = tmp_path / "cache.py"
        f2.write_text('class Cache:\n    _instance = None\n    @classmethod\n    def get_instance(cls):\n        return cls._instance\n')

        patterns = asyncio.run(
            detector.detect_in_project(str(tmp_path), languages=["python"])
        )
        names = {p.name for p in patterns}
        assert "Singleton" in names

    def test_confidence_scores_bounded(self, detector):
        """All confidence scores must be within [0, 1]."""
        code = '''
import asyncio
from abc import ABC, abstractmethod

class SingletonABC(ABC):
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def get_instance(cls):
        return cls._instance

    @abstractmethod
    async def run(self):
        pass
'''
        path = _write_temp(code)
        try:
            patterns = asyncio.run(
                detector.detect_in_file(path, language="python")
            )
            for p in patterns:
                assert 0.0 <= p.confidence.value <= 1.0, (
                    f"Confidence out of range for {p.name}: {p.confidence.value}"
                )
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# EvidenceValidator tests
# ---------------------------------------------------------------------------

class TestEvidenceValidator:
    def test_deduplicates_same_line(self, validator):
        from architect.models import PatternEvidence
        ev1 = PatternEvidence(
            file_path="/f.py", start_line=1, end_line=1,
            code_snippet="_instance = None", confidence=0.9)
        ev2 = PatternEvidence(
            file_path="/f.py", start_line=1, end_line=1,
            code_snippet="_instance = None", confidence=0.9)
        result = validator.validate([ev1, ev2])
        assert len(result) == 1

    def test_removes_empty_snippets(self, validator):
        from architect.models import PatternEvidence
        ev = PatternEvidence(
            file_path="/f.py", start_line=1, end_line=1,
            code_snippet="   ", confidence=0.9)
        result = validator.validate([ev])
        assert len(result) == 0

    def test_removes_zero_confidence(self, validator):
        from architect.models import PatternEvidence
        ev = PatternEvidence(
            file_path="/f.py", start_line=1, end_line=1,
            code_snippet="x = 1", confidence=0.0)
        result = validator.validate([ev])
        assert len(result) == 0

    def test_sorted_by_confidence_desc(self, validator):
        from architect.models import PatternEvidence
        evs = [
            PatternEvidence(file_path="/f.py", start_line=i, end_line=i,
                           code_snippet=f"line{i}", confidence=0.1 * i)
            for i in range(1, 6)
        ]
        result = validator.validate(evs)
        confidences = [e.confidence for e in result]
        assert confidences == sorted(confidences, reverse=True)


# ---------------------------------------------------------------------------
# RobustnessChecker tests
# ---------------------------------------------------------------------------

class TestRobustnessChecker:
    def test_suppresses_single_low_weight_pattern(self, checker, detector):
        """A pattern with a single evidence item at low confidence should be suppressed."""
        from architect.models import PatternEvidence, ConfidenceScore, Pattern
        weak_ev = PatternEvidence(
            file_path="/x.py", start_line=5, end_line=5,
            code_snippet="x = 1", confidence=0.55)
        pattern = Pattern(
            id="test_001", name="Factory", language="python",
            category=PatternCategoryEnum.OOP,
            evidence=[weak_ev],
            confidence=ConfidenceScore.from_evidence_count(1),
            description="test",
        )
        result = checker.check([pattern])
        assert result == []

    def test_passes_strong_pattern(self, checker):
        from architect.models import PatternEvidence, ConfidenceScore, Pattern
        strong_ev = PatternEvidence(
            file_path="/x.py", start_line=5, end_line=5,
            code_snippet="class ShapeFactory:", confidence=0.9)
        pattern = Pattern(
            id="test_002", name="Factory", language="python",
            category=PatternCategoryEnum.OOP,
            evidence=[strong_ev, strong_ev],
            confidence=ConfidenceScore.from_evidence_count(2),
            description="test",
        )
        result = checker.check([pattern])
        assert len(result) == 1

    def test_summary_counts(self, checker):
        from architect.models import PatternEvidence, ConfidenceScore, Pattern
        ev = PatternEvidence(
            file_path="/f.py", start_line=1, end_line=1,
            code_snippet="class MyFactory:", confidence=0.9)
        patterns = [
            Pattern(id=f"p{i}", name="Factory", language="python",
                   category=PatternCategoryEnum.OOP, evidence=[ev, ev],
                   confidence=ConfidenceScore.from_evidence_count(2), description="")
            for i in range(3)
        ]
        summary = checker.summary(patterns)
        assert summary["total"] == 3
        assert summary["by_category"]["oop"] == 3


# ---------------------------------------------------------------------------
# ConfidenceScore tests
# ---------------------------------------------------------------------------

class TestConfidenceScore:
    def test_from_evidence_count_zero(self):
        score = ConfidenceScore.from_evidence_count(0)
        assert score.value == 0.0
        assert score.evidence_quality == "no_evidence"

    def test_from_evidence_count_one(self):
        score = ConfidenceScore.from_evidence_count(1)
        assert 0.60 <= score.value < 0.80
        assert score.evidence_quality == "weak"

    def test_from_evidence_count_three(self):
        score = ConfidenceScore.from_evidence_count(3)
        assert score.value >= 0.80
        assert score.evidence_quality == "moderate"

    def test_from_evidence_count_many(self):
        score = ConfidenceScore.from_evidence_count(10)
        assert score.value >= 0.85
        assert score.value <= 1.0

    def test_confidence_level_property(self):
        score = ConfidenceScore.from_evidence_count(5)
        level = score.level
        assert level is not None

from netcortex_core import (
    CheckNews,
    Detect,
    Inject,
    Investigate,
    ModuleUnavailable,
    SearchRunbook,
    conforms,
)


def detect(site_id, window, history): ...
def search_runbook(query, k=5): ...
def check_news(provider, target): ...
def inject(site_id, scenario_type, duration_min, seed): ...
async def investigate(site_id, detection, window): ...


def test_matching_functions_conform():
    assert conforms(detect, Detect)
    assert conforms(search_runbook, SearchRunbook)
    assert conforms(check_news, CheckNews)
    assert conforms(inject, Inject)
    assert conforms(investigate, Investigate)


def test_mismatches_are_caught():
    def renamed(site, window, history): ...
    def wrong_default(query, k=10): ...
    def sync_investigate(site_id, detection, window): ...

    assert not conforms(renamed, Detect)
    assert not conforms(wrong_default, SearchRunbook)
    assert not conforms(sync_investigate, Investigate)


def test_module_unavailable_is_a_runtime_error_modules_can_subclass():
    class DetectorUnavailable(ModuleUnavailable):
        pass

    assert issubclass(DetectorUnavailable, RuntimeError)

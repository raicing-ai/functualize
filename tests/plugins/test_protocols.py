"""Tests for the Surface and PromptCollector protocols (core interactivity).

These are the two 1-method protocols that replaced InputProvider /
OutputRenderer. They are independent by design: a surface renders events
(``handle_event``) and a collector answers prompts (``collect``); an object
may satisfy either or both.
"""

from __future__ import annotations

from functualize._types.interactivity import PromptCollector, Surface, needs_terminal


class TestSurfaceProtocol:
    """Tests for the Surface @runtime_checkable Protocol."""

    def test_class_with_handle_event_passes_isinstance(self):
        class MySurface:
            def handle_event(self, event):
                pass

        assert isinstance(MySurface(), Surface)

    def test_class_missing_handle_event_fails_isinstance(self):
        class MissingHandleEvent:
            def collect(self, request):
                pass

        assert not isinstance(MissingHandleEvent(), Surface)

    def test_empty_class_fails_isinstance(self):
        class EmptyPlugin:
            pass

        assert not isinstance(EmptyPlugin(), Surface)


class TestPromptCollectorProtocol:
    """Tests for the PromptCollector @runtime_checkable Protocol."""

    def test_class_with_collect_passes_isinstance(self):
        class MyCollector:
            def collect(self, request):
                pass

        assert isinstance(MyCollector(), PromptCollector)

    def test_class_missing_collect_fails_isinstance(self):
        class MissingCollect:
            def handle_event(self, event):
                pass

        assert not isinstance(MissingCollect(), PromptCollector)

    def test_wrong_method_name_fails_isinstance(self):
        """A 'prompt' method (the old name) does not satisfy the protocol."""

        class WrongMethod:
            def prompt(self, request):
                pass

        assert not isinstance(WrongMethod(), PromptCollector)


class TestProtocolIndependence:
    """The two capabilities are independent; the split is load-bearing."""

    def test_flow_viz_renders_but_is_never_a_collector(self):
        """flow-viz renders and must NOT be handed prompts it cannot answer.

        This is the regression the two-protocol split exists to prevent: a
        fused protocol would force flow-viz to stub collect(), and since it
        auto-loads it would then win prompt resolution and swallow prompts.

        Since the surface-architecture conversion the rendering half is the
        hosted ``FlowVizConstruct`` (it consumes events, so it satisfies
        ``Surface``); the plugin object is now just the registrar. Neither may
        ever satisfy ``PromptCollector``.
        """
        from functualize_flow_viz import FlowVizConstruct, FlowVizPlugin

        construct = FlowVizConstruct()
        assert isinstance(construct, Surface)
        assert not isinstance(construct, PromptCollector)
        assert not isinstance(FlowVizPlugin(), PromptCollector)

    def test_stdin_collector_is_a_collector_but_not_a_surface(self):
        from functualize._engine.capabilities.stdin_collector import StdinCollector

        collector = StdinCollector()
        assert isinstance(collector, PromptCollector)
        assert not isinstance(collector, Surface)

    def test_object_can_satisfy_both(self):
        class FullSurface:
            def handle_event(self, event):
                pass

            def collect(self, request):
                pass

        obj = FullSurface()
        assert isinstance(obj, Surface)
        assert isinstance(obj, PromptCollector)

    def test_needs_terminal_defaults_true(self):
        class BareSurface:
            def handle_event(self, event):
                pass

        assert needs_terminal(BareSurface()) is True

    def test_needs_terminal_respects_opt_out(self):
        class Headless:
            needs_terminal = False

            def handle_event(self, event):
                pass

        assert needs_terminal(Headless()) is False

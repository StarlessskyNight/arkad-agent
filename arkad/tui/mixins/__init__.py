"""Feature mixins for the Arkad TUI App.

Each mixin groups a cohesive cluster of ``ArkadTUI`` behaviour (and its
instance state) into its own module so the main app class stays navigable.
Mixins are not standalone widgets — they assume ``self`` is the composed
``ArkadTUI`` instance and rely on methods/attributes provided by it.
"""

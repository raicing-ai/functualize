# functualize-decision-jev

> **Status: Tier 3 — experimental.** The Phase 1 decision-provider adapter;
> requires `OPENCODE_API_KEY`. It proposes a candidate answer to a `choice`
> question through the Jev model service, and the gate that asked applies its
> own declared thresholds — the provider never decides whether its proposal is
> acted on. The package is an empty scaffold today: the provider, its wire
> mapping and the plugin that registers the `decision` gate strategy arrive in
> later steps of the same change.

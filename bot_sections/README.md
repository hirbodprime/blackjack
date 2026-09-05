# Bot source sections

These files are loaded in the order declared in the top-level `blackjack.py`.
They share one global namespace on purpose. This preserves the behavior of the
original monolithic module, including late global lookups, handler registration
order, and polling startup.

Keep top-level executable statements in their existing order. Functions may
call functions declared in later sections because those names are resolved when
the function runs. Moving a top-level statement across sections can change
startup behavior and should be covered by a compatibility test first.

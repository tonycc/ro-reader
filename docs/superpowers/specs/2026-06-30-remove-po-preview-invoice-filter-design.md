# Remove PO Preview Invoice Filter

## Problem

The PO preview scope now supports only PI and PO documents, but its filter bar still renders the legacy invoice-number selector. Because Invoice and PL moved to the Invoice scope, the selector has no valid PO-scope operation and remains disabled.

## Design

- Remove the invoice-number filter group from the PO preview filter bar.
- Remove component-local computed state and change handling used only by that selector when they have no remaining consumers.
- Keep Invoice-scope group selection, Invoice/PL document switching, preview requests, and export behavior unchanged.
- Do not hide the control with CSS; remove the obsolete UI and dead component code.

## Verification

- Add an end-to-end assertion that the PO preview contains no invoice selector.
- Retain the existing Invoice-scope preview coverage.
- Run the focused end-to-end scenario, the frontend build, and the full end-to-end suite.


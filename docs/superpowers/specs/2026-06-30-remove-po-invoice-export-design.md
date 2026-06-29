# Remove Invoice Export From PO Scope

## Problem

Invoice and PL now belong to the Invoice workbench scope, but the PO export screen still builds an `INVOICE_PL` entry for each seller and exposes the legacy invoice-number selector. This lets the PO scope offer documents that are owned by another scope.

## Design

- The PO export screen exposes only PI and PO entries.
- The PO preview defaults to PI and accepts only PI/PO document state, so its preview body and quick-export button cannot leak Invoice/PL from another scope.
- SK and YM continue to omit PO because those sellers have no PO template.
- Remove PO-export component state, helpers, template markup, and CSS used only for invoice-number selection and `INVOICE_PL` entries.
- Keep the Invoice-scope export branch unchanged: it continues to offer independent Invoice and PL selections and uses the invoice-group export API.
- Do not change core, API, or CLI export contracts in this fix.

## Verification

- Extend the PO export E2E scenario to assert that no `INVOICE_PL` entry or PO-scope invoice selector is rendered.
- Cover the first-entry PO preview path without manually selecting PI; assert that it shows a PI preview and a PI quick-export button, never Invoice/PL.
- Retain the existing Invoice-scope export scenario and verify Invoice and PL remain available there.
- Run the focused regression, frontend build, and full E2E suite.

# Export Confirmation State Design

## Goal

Make export confirmation independent from document preview: each seller has its own document and invoice selection, and the selected entries are generated as one ZIP file.

## Current Problem

`selectedSeller` and `selectedInvoiceNo` belong to the preview state. The export confirmation page builds its seller groups independently, but the batch request reuses the preview state for the currently selected seller. This can make the displayed Invoice/PL filename disagree with the invoice that is actually exported.

## Design

- The confirmation page owns a local export selection for every seller in the selected PO.
- Each seller group has a normal invoice dropdown that is shown when Invoice/PL is exportable. It uses that seller's available invoice options and defaults to its first option.
- The document checkboxes and invoice dropdown together form the `groups` payload for `/export-batch`.
- Changing the preview seller or preview invoice has no effect on confirmation-page selections.
- The confirmation-page filename uses the same group invoice selected for the batch request.
- PI and PO retain no invoice selector. Sellers without an exportable Invoice/PL retain no selectable Invoice/PL entry.

## Validation

- Frontend E2E verifies that preview invoice selection does not change confirmation-page invoice selection.
- Frontend E2E verifies the batch request contains each selected seller's own invoice number.
- Existing API/core ZIP tests continue to verify one downloaded ZIP contains the selected Excel files.

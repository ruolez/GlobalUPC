# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Owner and office / warehouse staff of a wholesale distribution business that runs several BackOffice (MSSQL) databases and several Shopify storefronts. They keep the app open during the working day on office desktop monitors and laptops, and also open it on tablets and phones. The owner uses the password-protected Business Overview; staff use the UPC, pricing, shipment and report tools.

## Product Purpose

One place to keep every store consistent and to see what the business is doing: fix a barcode or a price in every store at once, follow quotations through picking and packing, reconcile BackOffice invoices with Shopify orders, and read sales, margin, purchasing and month-end figures across all stores.

## Positioning

It reads and writes the company's own BackOffice databases and Shopify stores side by side, so a number on screen can always be traced to the invoice, order or item behind it.

## Operating Context

- Used on the office LAN over plain HTTP; other internal apps call its `/api/`.
- Many reports query live MSSQL and Shopify and take seconds to minutes; progress is streamed.
- Several actions change live data (UPC and price updates, Shopify order fixes, cancellations), so what will change must be clear before it runs.
- Staff compare identifiers digit by digit: UPCs, invoice, quotation and tracking numbers.

## Capabilities and Constraints

- Vanilla HTML / CSS / JS single-page app, no build step: `frontend/src/index.html`, `app.js`, `styles.css`.
- Eight colour themes built on CSS variables; the default is the light "Author's Light" theme. New UI uses only the shared tokens so every theme keeps working.
- No external network dependencies at page load: fonts and libraries are served from the app itself.
- Screen sizes in use: desktop monitors, laptops (about 1100-1366 px wide, 700-800 px tall), tablets and phones.

## Brand Commitments

- Name: Global UPC. Mark: a barcode.
- Visual identity (confirmed November 2026): keep and refine the current look, warm paper neutrals with a green accent; keep all eight themes.
- Feature names and navigation stay where staff expect them; changes to flow are improvements inside each page, not a reorganisation.

## Product Principles

1. The same thing looks and behaves the same on every page.
2. Numbers are the content: aligned, comparable, traceable to their source.
3. Nothing that changes live data happens without a clear statement of what will change.
4. One slow or failing store never blanks a page; states (loading, empty, error, stale) are always shown.
5. Dense is fine; unclear is not.

## Accessibility & Inclusion

Target WCAG 2.2 AA: 4.5:1 text contrast in every theme, visible keyboard focus, dialogs that trap focus and close on Escape, labelled form fields, reduced-motion support.

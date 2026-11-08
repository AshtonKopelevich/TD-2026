# Static dashboard for judges

Generate the site from the real, built database:

```powershell
uv run --extra dashboard python export_dashboard.py
```

The exporter renders the opening page, all seven chapters and every linked
machine detail page. It bundles Plotly, embeds each chart's data, converts links
to relative HTML paths, replaces server filters with a scope notice and removes
external font requests. No database or application server is deployed.

Open `sites/gilded-ace/dist/index.html`, or publish the contents of that `dist`
directory to a static host. Explicit HTML links also support hosts that place
the site under a subdirectory. The Sites deployment is configured in
`sites/gilded-ace/.openai/hosting.json`.

The site preserves saved findings, chart interactions, sortable tables,
expandable details, machine drill-downs and theme selection. Filters are fixed
to January–June 2025 and the whole floor. Updating findings requires rebuilding
the database, exporting again and redeploying the static files.

Validate an existing export without rendering it again:

```powershell
uv run --extra dashboard python export_dashboard.py --check
```

`export-manifest.json` in the output records generation time, database modification
time and exported routes. Only the static output is uploaded; the DuckDB database
and raw sources remain local.

## Redeploy after dashboard changes

Run the export command again, then ask Codex to redeploy the existing Gilded Ace
Site using the Sites plugin. Exporting alone only updates local files. The
publishing workflow pushes the updated Site source, packages it, saves a new
version and deploys it. The public URL stays the same.

If only templates, styles or narrative text changed, no pipeline rebuild is
needed. If the analysis or data changed, rebuild the database before exporting.

## Take the site offline after judging

In ChatGPT, open **Sites**, select **The Gilded Ace**, and use **Share** to restrict
access to just yourself. This removes public access while keeping the Site for
later use. You can also ask Codex to make the existing Site private.

To remove the hosted Site permanently, select **Delete site** and complete the
confirmation. Deletion cannot be undone. The project files in this repository
remain available independently of the hosted Site.

Official instructions:
https://help.openai.com/en/articles/20001339-creating-and-using-chatgpt-sites

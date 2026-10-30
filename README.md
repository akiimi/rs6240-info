# RS6240 occupancy guide

A single-page guide to the RS6240 radar SDK, its configuration parameters, and the occupancy ML pipeline.

| File | What to edit it for |
| --- | --- |
| `guide.md` | All content. Standard Markdown; `## Heading {#id}` sets a section's link. |
| `template.html` | Look and behaviour. Colours and fonts are CSS variables in the `:root` block at the top. |
| `build.py` | Title, subtitle and "Edit on GitHub" link (the `CONFIG` block). |
| `index.html` | Generated. Do not edit by hand. |

## Publish on GitHub Pages (one time, about 5 minutes)

1. On github.com, create a new repository (for example `rs6240-guide`). Public works on any plan; private repositories need a paid plan for Pages.
2. Upload every file in this folder, including the hidden `.github/workflows/pages.yml` (drag the whole folder into "uploading an existing file", or use `git push`).
3. Open the repository's **Settings → Pages**, and under **Build and deployment → Source**, choose **GitHub Actions**.
4. Open the **Actions** tab and wait for "Publish guide to GitHub Pages" to finish (about 1 minute). If it ran before step 3, click it and choose **Re-run all jobs**.
5. The page is live at `https://<your-username>.github.io/<repo-name>/`. The link is also shown in **Settings → Pages**.

After that, editing `guide.md` on GitHub (pencil icon) and committing republishes the page automatically.

Optional: set `EDIT_URL` in `build.py` to `https://github.com/<user>/<repo>/edit/main/guide.md` to show an "Edit on GitHub" link in the page header.

## Build locally

```bash
pip install -r requirements.txt
python build.py        # writes index.html
```

Open `index.html` in a browser to preview.

## Page features

- Searchable contents sidebar (press `/` to search; Enter for next match).
- Light / dark / auto theme and text size, remembered per browser.
- Copy buttons on all code blocks.
- Roadmap checkboxes, remembered per browser.
- Print / Save as PDF layout.

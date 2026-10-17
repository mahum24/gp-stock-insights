"""The one-page HTML dashboard.

    python -m gpstock.report      # writes docs/index.html
"""
import duckdb
import plotly.express as px
import plotly.graph_objects as go

from gpstock import DATA_DIR, ROOT

SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
CATEGORIES = ["Medical Consumables", "Cleaning & Hygiene", "PPE", "Stationery & Office", "Medical Equipment",
              "Tea & Coffee", "Kitchen & Pantry", "Milk & Dairy"]
LAYOUT = dict(font=dict(family="Inter, system-ui, sans-serif", color="#0b0b0b", size=13),
              paper_bgcolor="#fcfcfb", plot_bgcolor="#fcfcfb", margin=dict(l=8, r=8, t=56, b=8),
              xaxis=dict(showgrid=False, linecolor="#c3c2b7", tickfont=dict(color="#898781")),
              yaxis=dict(gridcolor="#e1e0d9", zeroline=False, tickfont=dict(color="#898781")),
              legend=dict(orientation="h", y=1.1, x=0, title=None), height=360, title_font_size=15)


def fig_html(fig, first=False):
    fig.update_layout(**LAYOUT)
    return fig.to_html(full_html=False, include_plotlyjs="cdn" if first else False, default_width="100%",
                       config={"displayModeBar": False, "responsive": True})


def build_report(con: duckdb.DuckDBPyConnection) -> str:
    k = con.execute("""
        SELECT sum(spend_gbp) AS spend, sum(waste_gbp) AS waste,
               sum(waste_gbp) / (sum(waste_gbp) + sum(value_gbp) FILTER (WHERE movement_kind = 'used')) AS waste_pct
        FROM fact_movement""").df().iloc[0]
    avail = con.execute("""SELECT avg((NOT out_of_stock)::INT) FROM fact_daily_stock JOIN dim_date USING (date)
                           WHERE is_open_day""").fetchone()[0]
    review = con.execute("SELECT avg(hours_to_review) FROM fact_request WHERE priority = 'normal'").fetchone()[0]
    urgent = con.execute("SELECT avg(hours_to_review) FROM fact_request WHERE priority = 'urgent'").fetchone()[0]

    spend = con.execute("""SELECT d.month, i.category, sum(f.spend_gbp) AS spend
                           FROM fact_movement f JOIN dim_date d USING (date) JOIN dim_item i USING (item_id)
                           GROUP BY ALL ORDER BY d.month""").df()
    f1 = px.bar(spend, x="month", y="spend", color="category", title="Monthly spend by category",
                category_orders={"category": CATEGORIES}, color_discrete_sequence=SERIES,
                labels={"spend": "£", "month": "", "category": ""})
    f1.update_traces(marker_line_color="#fcfcfb", marker_line_width=1, hovertemplate="%{x|%b %Y}: £%{y:,.0f}")

    waste = con.execute("""SELECT i.item, sum(f.waste_gbp) AS waste FROM fact_movement f JOIN dim_item i USING (item_id)
                           GROUP BY 1 HAVING sum(f.waste_gbp) > 0 ORDER BY 2 DESC LIMIT 10""").df()
    f2 = px.bar(waste.iloc[::-1], x="waste", y="item", orientation="h", title="Where waste comes from (expired, damaged, lost)",
                labels={"waste": "£ wasted", "item": ""}, color_discrete_sequence=SERIES[:1])
    f2.update_traces(hovertemplate="%{y}: £%{x:,.2f}<extra></extra>")
    f2.update_xaxes(range=[0, waste.waste.max() * 1.08], tickprefix="£")

    out = con.execute("""SELECT i.item || ' (' || s.site || ')' AS item, p.days_out_of_stock
                         FROM mart_item_performance p JOIN dim_item i USING (item_id) JOIN dim_site s USING (site_id)
                         WHERE p.days_out_of_stock > 0 ORDER BY 2 DESC LIMIT 10""").df()
    f3 = px.bar(out.iloc[::-1], x="days_out_of_stock", y="item", orientation="h", title="Open days with no stock",
                labels={"days_out_of_stock": "Days", "item": ""}, color_discrete_sequence=SERIES[1:2])
    f3.update_traces(hovertemplate="%{y}: %{x} days<extra></extra>")
    f3.update_xaxes(range=[0, out.days_out_of_stock.max() * 1.08])

    use = con.execute("""SELECT d.month, CASE WHEN i.is_clinical THEN 'Clinical items' ELSE 'Non-clinical items' END AS kind,
                                sum(f.value_gbp) AS used
                         FROM fact_movement f JOIN dim_date d USING (date) JOIN dim_item i USING (item_id)
                         WHERE f.movement_kind = 'used' GROUP BY ALL ORDER BY d.month""").df()
    f4 = px.line(use, x="month", y="used", color="kind", title="Value of stock used each month (winter flu season Oct-Feb)",
                 labels={"used": "£", "month": "", "kind": ""}, color_discrete_sequence=SERIES,
                 category_orders={"kind": ["Clinical items", "Non-clinical items"]})
    f4.update_traces(line_width=2, hovertemplate="%{x|%b %Y}: £%{y:,.0f}")
    f4.update_layout(hovermode="x unified")

    watch = con.execute("""SELECT i.item, s.site, b.batch_number, b.expiry_date, b.quantity_now, b.value_now_gbp
                           FROM fact_batch b JOIN dim_item i USING (item_id) JOIN dim_site s USING (site_id)
                           WHERE b.expiry_status = 'Expiring within 60 days' ORDER BY b.expiry_date""").df()
    rows = "".join(f"<tr><td>{r.item}</td><td>{r.site}</td><td>{r.batch_number}</td><td>{r.expiry_date:%d %b %Y}</td>"
                   f"<td class=n>{r.quantity_now}</td><td class=n>£{r.value_now_gbp:,.2f}</td></tr>" for r in watch.itertuples())

    tiles = [("Spend this year", f"£{k.spend:,.0f}"), ("Waste", f"£{k.waste:,.0f}"),
             ("Waste as share of stock used", f"{k.waste_pct:.1%}"), ("Shelf availability", f"{avail:.1%}"),
             ("Time to approve a request", f"{review:.0f}h ({urgent:.0f}h if urgent)")]
    tile_html = "".join(f"<div class=tile><div class=label>{a}</div><div class=value>{b}</div></div>" for a, b in tiles)

    return f"""<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width, initial-scale=1"><title>GP Stock Insights</title>
<style>
:root{{--bg:#f9f9f7;--card:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--line:#e1e0d9}}
body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 Inter,system-ui,sans-serif}}
main{{max-width:1180px;margin:0 auto;padding:32px 16px 64px}}
h1{{margin:0 0 4px;font-size:28px}} p.sub{{margin:0 0 24px;color:var(--ink2)}}
.tiles{{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin-bottom:16px}}
.tile,.card{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px}}
.label{{color:var(--ink2);font-size:13px}} .value{{font-size:24px;font-weight:600;margin-top:2px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(420px,1fr));gap:16px;margin-bottom:16px}}
.card{{min-width:0;overflow:hidden}}
@media (max-width:520px){{.grid{{grid-template-columns:1fr}}}}
table{{width:100%;border-collapse:collapse;font-size:14px}} th,td{{text-align:left;padding:8px;border-bottom:1px solid var(--line)}}
th{{color:var(--ink2);font-weight:500}} td.n{{text-align:right;font-variant-numeric:tabular-nums}}
.note{{color:var(--ink2);font-size:13px;margin-top:24px}}
</style></head><body><main>
<h1>GP Stock Insights</h1>
<p class=sub>Riverside Medical Practice · two sites · 1 Oct 2025 to 30 Sep 2026</p>
<div class=tiles>{tile_html}</div>
<div class=card>{fig_html(f1, first=True)}</div><br>
<div class=grid><div class=card>{fig_html(f2)}</div><div class=card>{fig_html(f3)}</div></div>
<div class=card>{fig_html(f4)}</div><br>
<div class=card><h3 style="margin:4px 0 8px;font-size:15px">Expiry watch list: batches expiring in the next 60 days</h3>
<table><thead><tr><th>Item</th><th>Site</th><th>Batch</th><th>Expires</th><th class=n>Qty</th><th class=n>Value</th></tr></thead>
<tbody>{rows or '<tr><td colspan=6>Nothing expiring soon.</td></tr>'}</tbody></table></div>
<p class=note>The same model loads into Power BI from <code>data/powerbi/GP_Stock_PowerBI.xlsx</code>.</p>
</main>
<script>
// Charts in the two-column row can be drawn before the grid settles; fit each to its card once loaded.
window.addEventListener("load", () => document.querySelectorAll(".js-plotly-plot").forEach(d => Plotly.Plots.resize(d)));
</script></body></html>"""


def main():
    con = duckdb.connect(str(DATA_DIR / "gp_stock.duckdb"), read_only=True)
    out = ROOT / "docs" / "index.html"
    out.parent.mkdir(exist_ok=True)
    out.write_text(build_report(con))
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()

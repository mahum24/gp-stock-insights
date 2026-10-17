# Building the GP Stock Insights report in Power BI (browser)

Works at [app.powerbi.com](https://app.powerbi.com) with a Microsoft Fabric (free) account. No Windows needed.

## 1. Upload the data
1. Run `python -m gpstock.build --generate`. It writes `data/powerbi/GP_Stock_PowerBI.xlsx`.
2. In Power BI, go to **My workspace → New item → Semantic model** (or **Upload**), choose the Excel file, and import all 9 tables.

## 2. Relationships (open the semantic model → **Open data model**)
All one-to-many, single direction, from dimension to fact:

| From (one) | To (many) |
|---|---|
| DimDate[date] | FactMovement[date], FactDailyStock[date], FactRequest[date] |
| DimItem[item_id] | FactMovement, FactDailyStock, FactRequest, FactBatch, ItemPerformance [item_id] |
| DimSite[site_id] | FactMovement, FactDailyStock, FactRequest, FactBatch, ItemPerformance [site_id] |
| DimStaff[user_id] | FactMovement[user_id] |

Delete any relationship Power BI guessed between two fact tables.

## 3. Measures
Select **FactMovement → New measure** and paste each measure from [`measures.dax`](measures.dax).
Format money as **Currency (£)** and the `%` measures as **Percentage**.

## 4. Report pages

**Page 1: Stock overview**
- Cards: Spend, Waste Value, Waste %, Availability %, Items Below Reorder Today
- Clustered column: Spend by DimDate[month], legend DimItem[category]
- Bar: Waste Value by DimItem[item] (top 10, Top N filter)
- Slicers: DimSite[site], DimItem[category]

**Page 2: Availability**
- Bar: Stockout Days by DimItem[item] (top 10)
- Line: Units Used by DimDate[month], legend DimItem[is_clinical] (shows the winter flu-season rise)
- Matrix: DimItem[item] × DimSite[site] with Stockout Days, and conditional formatting

**Page 3: Ordering & expiry**
- Cards: Average Hours to Approve, Average Days to Arrive, Urgent Request %
- Column: Average Hours to Approve by FactRequest[priority]
- Table: FactBatch filtered to expiry_status = "Expiring within 60 days" with item, site, batch_number,
  expiry_date, quantity_now, value_now_gbp (an expiry watch list)

Keep one colour per category on every page, and save screenshots of each page into `docs/`.

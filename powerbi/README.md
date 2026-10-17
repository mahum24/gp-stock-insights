# GP Stock Insights Power BI model

Nine tables in a star schema, a DAX measure library and three report pages.

## 1. Data
`python -m gpstock.build --generate` writes `data/powerbi/GP_Stock_PowerBI.xlsx`. Import it into Power BI as a semantic model (**New item → Semantic model → Excel**); all 9 tables load.

## 2. Relationships
All one-to-many, single direction, from dimension to fact:

| From (one) | To (many) |
|---|---|
| DimDate[date] | FactMovement[date], FactDailyStock[date], FactRequest[date] |
| DimItem[item_id] | FactMovement, FactDailyStock, FactRequest, FactBatch, ItemPerformance [item_id] |
| DimSite[site_id] | FactMovement, FactDailyStock, FactRequest, FactBatch, ItemPerformance [site_id] |
| DimStaff[user_id] | FactMovement[user_id] |

There are no relationships between fact tables.

## 3. Measures
All measures are in [`measures.dax`](measures.dax) and live on **FactMovement**.
Money is formatted as **Currency (£)** and the `%` measures as **Percentage**.

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

Each category keeps one colour on every page.

| 特征名 | 来源表 | 计算方式 |
|--------|--------|----------|
| age_group | t_customer | 直接取值 |
| city | t_customer | 直接取值 |
| occupation | t_customer | 直接取值 |
| income_level | t_customer | 直接取值 |
| vip_level | t_customer | 直接取值 |
| channel | 构造 | A2 产品排序时固定为 manager |
| product_type | t_product | 直接取值 |
| liquidity | t_product | 直接取值 |
| risk_match_bin | t_customer, t_product | abs_risk_diff=0→exact；=1→near；否则 far |
| seg_risk_income | t_customer | risk_appetite + "\|" + income_level |
| risk_n_c | t_customer | risk_appetite 映射：R1→1, R2→2, R3→3, R4→4, R5→5 |
| has_app | t_customer | 直接取值（0/1） |
| log_aum | t_customer | log1p(aum) |
| vip_n | t_customer | vip_level 映射：普通→0, 银卡→1, 金卡→2, 钻石→3 |
| risk_n_p | t_product | risk_level 映射：R1→1 … R5→5 |
| expected_return | t_product | 直接取值 |
| volatility | t_product | 直接取值 |
| log_min_invest | t_product | log1p(min_invest) |
| duration_days | t_product | 直接取值 |
| liq_n | t_product | liquidity 映射：T+0→2, T+1→1, 封闭→0 |
| abs_risk_diff | t_customer, t_product | \|risk_n_c − risk_n_p\| |
| signed_risk_diff | t_customer, t_product | risk_n_c − risk_n_p |
| risk_exact_match | t_customer, t_product | abs_risk_diff = 0 时为 1，否则 0 |
| risk_within_1 | t_customer, t_product | abs_risk_diff ≤ 1 时为 1，否则 0 |
| aum_over_min | t_customer, t_product | aum / min_invest |
| can_afford | t_customer, t_product | aum ≥ min_invest 时为 1，否则 0 |
| return_over_vol | t_product | expected_return / volatility |
| return_risk_align | t_customer, t_product | expected_return × risk_n_c |
| app_x_push | t_customer, 构造 | has_app=1 且 channel=app_push 时为 1，否则 0 |
| vip_x_return | t_customer, t_product | vip_n × expected_return |
| vip_x_risk_p | t_customer, t_product | vip_n × risk_n_p |
| hold_n | t_holding | 按 customer_id 统计 count(distinct product_id) |
| log_hold_amt | t_holding | 按 customer_id 统计 log1p(sum(amount)) |
| held_n | t_holding | 按 (customer_id, product_id) 统计持仓笔数 |
| already_held | t_holding | held_n > 0 时为 1，否则 0 |
| cust_camp_n | t_campaign | 按 customer_id 统计触达次数 |
| cust_camp_pos | t_campaign | 按 customer_id 统计 sum(responded) |
| cust_resp_rate | t_campaign | cust_camp_pos / cust_camp_n |
| cp_camp_n | t_campaign | 按 (customer_id, product_id) 统计触达次数 |
| cp_camp_pos | t_campaign | 按 (customer_id, product_id) 统计 sum(responded) |
| cp_resp_rate | t_campaign | cp_camp_pos / cp_camp_n |
| prod_resp_rate | t_campaign | 按 product_id 统计 mean(responded) |
| chan_resp_rate | t_campaign | 按 channel 统计 mean(responded) |
| prod_chan_resp_rate | t_campaign | 按 (product_id, channel) 统计 mean(responded) |
| seg_prod_rate | t_campaign, t_customer | 按 (seg_risk_income, product_id) 统计 mean(responded) |
| seg_type_rate | t_campaign, t_customer, t_product | 按 (seg_risk_income, product_type) 统计 mean(responded) |
| risk_prod_rate | t_campaign, t_customer | 按 (risk_appetite, product_id) 统计 mean(responded) |
| type_hold_share | t_holding, t_product | 客户该 product_type 持仓数 / 客户总持仓产品数 |
| ev_login | t_event | 按 customer_id 统计 event_type=login 次数 |
| ev_consult | t_event | 按 customer_id 统计 event_type=consult 次数 |
| ev_complaint | t_event | 按 customer_id 统计 event_type=complaint 次数 |
| ev_active | t_event | ev_login + ev_consult |

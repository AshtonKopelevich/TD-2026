"""Period-level player outcomes; signed net and gross-loss concentration are separate."""


def build_player_diagnostics(con):
    con.execute("""CREATE TABLE diagnostics.player_outcomes AS
    WITH per_player AS (
      SELECT player_id,sum(tracked_coin_in_usd) AS coin,sum(actual_tracked_loss_usd) AS loss
      FROM marts.mart_player_month GROUP BY player_id
    ), ranked AS (
      SELECT *,row_number() OVER(ORDER BY greatest(loss,0) DESC,player_id) AS r,
      count(*) OVER() AS n FROM per_player WHERE coin>0
    ), totals AS (
      SELECT count(*)::BIGINT AS tracked_players,count(*) FILTER(WHERE coin>0)::BIGINT AS players_with_gaming,
      count(*) FILTER(WHERE loss<0)::BIGINT AS winning_players,
      coalesce(sum(greatest(loss,0)),0)::DECIMAL(24,2) AS gross_player_loss_usd,
      coalesce(sum(greatest(-loss,0)),0)::DECIMAL(24,2) AS gross_player_win_usd,
      coalesce(sum(loss),0)::DECIMAL(24,2) AS net_player_loss_usd FROM per_player
    ), shares AS (
      SELECT sum(CASE WHEN r<=ceil(n*0.01) THEN greatest(loss,0) ELSE 0 END)::DOUBLE/
        nullif(sum(greatest(loss,0)),0) AS top_1pct_gross_loss_share,
      sum(CASE WHEN r<=ceil(n*0.10) THEN greatest(loss,0) ELSE 0 END)::DOUBLE/
        nullif(sum(greatest(loss,0)),0) AS top_10pct_gross_loss_share FROM ranked
    ) SELECT w.start_date AS analysis_start,w.end_date AS analysis_end,t.*,
      winning_players::DOUBLE/nullif(players_with_gaming,0) AS winner_share_gaming_players,s.*
    FROM totals t CROSS JOIN shares s CROSS JOIN staging.analysis_window w""")

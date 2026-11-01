# Idea backlog

The lab takes the next `new` idea from here, by source priority: user → journal → seed → agent.
Line format and rules: `program.md`, section 5.3. Never delete a line; change its status.

## The user's ideas
<!-- add a line any time, e.g.: I-001 | new | user | behavioral | Hold bonds only when stocks fall | why -->
<!-- your own fail conditions go last, e.g.: ... | why | checks: orders_per_year > 12; val_maxdd > 0.15 -->
<!-- ids: one sequence for the whole file (I-001, I-002, ...), whoever adds the line -->

## Journal follow-ups

## Seed list
<!-- written 2026-10-31 from a separate research (the report: docs/seed-research.md). one line per expected family;
close variants are refines of that line, not new lines. order = priority: simple rules -> statistics, calendar ideas last.
"summary only" or "source not verified" = the paper itself wasn't opened. performance numbers in papers come from other universes. -->
I-001 | new | seed | behavioral | Hold each asset only while its price is above its own long moving average, else cash | trends persist because investors react slowly to news; Moskowitz-Ooi-Pedersen 2012 (JFE), Faber 2007 (JWM). Refines: 12-month return > 0 instead of the average; absolute momentum (Antonacci)
I-002 | new | seed | behavioral | Hold the top few assets by their 6-12 month return, equal weight, monthly | relative momentum: recent winners keep winning for months; Jegadeesh-Titman 1993 (JF, stocks). Refines: dual momentum (only if the return is also > 0)
I-003 | new | seed | risk | Weight each asset by 1 / its recent volatility, always invested, no leverage | equal risk instead of equal money: calm assets get more weight; Asness-Frazzini-Pedersen 2012 (FAJ), unlevered version
I-004 | new | seed | risk | Scale total exposure by target volatility / recent portfolio volatility, at most 100%, the rest in cash | volatility is easier to predict than returns, so cutting risk in stormy times lifts the Sharpe ratio; Moreira-Muir 2017 (JF)
I-005 | new | seed | behavioral | Move part of the money to the bond class in proportion to how many assets have negative momentum | when many assets fall at once, a crash is more likely; Keller-Keuning 2016 PAA, 2018 DAA (SSRN; summary only)
I-006 | new | seed | behavioral | Go to cash when an equal-weight portfolio of all assets is more than X% below its high; return when it recovers | losses tend to continue after a big fall; Kaminski-Lo 2014 (JFM)
I-007 | new | seed | risk | Long-only minimum-variance weights from a shrunk covariance of recent daily returns | low-risk assets aren't paid less than risky ones; Clarke-de Silva-Thorley 2006 (JPM; source not verified). Warning: DeMiguel-Garlappi-Uppal 2009: optimisers rarely beat 1/N
I-008 | new | seed | risk | Go to cash when cross-asset returns are statistically unusual (a high turbulence measure) | turbulent periods persist and risky assets earn less in them; Kritzman-Li 2010 (FAJ)
I-009 | new | seed | behavioral | Rank assets by momentum, low volatility and low correlation to the rest; hold the top 3 that have positive momentum | three known effects in one rank; Keller-van Putten 2012 FAA (SSRN; summary only). Probably the same family as I-002
I-010 | new | seed | risk | Markowitz weights with momentum as the expected return and shrunk risk estimates; drop assets with negative momentum | a long-only tactical portfolio; Keller-van Putten 2013 MAA (SSRN; summary only). Probably the same family as I-002 or I-007
I-011 | new | seed | behavioral | Buy the assets that fell most last month, equal weight, hold one month | short-term reversal after overreaction; Jegadeesh 1990 (JF, stocks). Expect the €1 order cost to eat it
I-012 | new | seed | behavioral | Hold the equity class from November to April and the bond class from May to October | "sell in May": a seasonal effect found in many countries; Bouman-Jacobsen 2002 (AER; citation checked, the cause is unknown)
I-013 | new | seed | structural | Hold the equity class only from the 25th to the 3rd of each month, else cash | returns concentrate around the turn of the month; McConnell-Xu 2008 (FAJ). Use calendar days: "the last trading day" needs the next day's row (lookahead)
I-014 | parked | seed | behavioral | A machine-learning model on price features (returns, volatility, drawdown) forecasts next month's asset returns | ML waits until the user opens it after the course; Gu-Kelly-Xiu 2020 (RFS, stocks)
I-015 | parked | seed | risk | Carry, yield-curve or value tilts across asset classes | needs data (yields, dividends, fundamentals); Koijen et al. 2018 (JFE; source not verified)

## Agent's ideas

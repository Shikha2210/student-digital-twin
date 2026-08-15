-- ============================================================
-- 002 - carry the PREDICT step's uncertainty, not only its mean
-- ------------------------------------------------------------
-- The filter computes a one-step-ahead prior P_pred = F P F' + Q and
-- keeps it (StateTrajectory.predicted_covs) so the RTS smoother does not
-- have to replay. 001 stored only the prior MEAN, which meant the
-- frontend could show where the model expected the student to be but not
-- how unsure it was on the way there.
--
-- That gap mattered for one specific reason: "predict widens the
-- uncertainty, update narrows it again" is the central claim of the
-- product, and without prior_sd the only way to draw it was to recompute
-- F P F' + Q in JavaScript. Reimplementing a model equation in the
-- browser to illustrate that equation is exactly the duplication this
-- architecture exists to prevent.
-- ============================================================

ALTER TABLE attribution_steps ADD COLUMN prior_sd REAL;
ALTER TABLE attribution_steps ADD COLUMN posterior_sd REAL;

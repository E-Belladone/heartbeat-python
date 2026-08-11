-- An example substance catalog + intake templates.
--
-- Applied after schema.sql and grants.sql, in the same transaction. This is an
-- *example*, not a recommendation: edit it to whatever you actually log. Every
-- half-life here is a population figure from the literature, and individual
-- clearance varies severalfold, so treat a drawn curve as an illustration of a
-- model rather than a measurement of a body.
--
-- Seed-ONCE, not re-seeded: each block only inserts while its table is still
-- empty (the WHERE NOT EXISTS guard). The first deploy populates the catalog and
-- every later one is a no-op, so edits made at runtime survive a redeploy.
--
-- Nothing about a real person is inferable from this file, and that is
-- deliberate. A substance catalog discloses a medical history by its
-- *membership* alone, before a single dose is recorded, so what a catalog
-- contains is not something to publish casually. If you fork this and add your
-- own substances, that property is yours to keep or to give up knowingly.

INSERT INTO substance.catalog (name, model_family, params, label, color, category, unit, unit_per_mg)
SELECT * FROM (VALUES
    -- Caffeine: t1/2 ~5 h, fasted tmax ~30 min; with food uptake slows to
    -- tmax ~2.5 h (fed_absorption 0.8 h, back-fit to Skinner 2013 fed 120-180
    -- min). Uptake, not clearance, is what the fed flag changes.
    ('caffeine', 'bateman', '{"half_life_hours": 5.0, "absorption_half_life_hours": 0.1, "fed_absorption_half_life_hours": 0.8}'::jsonb, 'Caffeine', 'foam', 'stimulant', 'mg', 1.0),
    ('melatonin', 'bateman', '{"half_life_hours": 0.75, "absorption_half_life_hours": 0.1}'::jsonb, 'Melatonin', 'pine', 'complement', 'mg', 1.0),
    -- vitamin B12: body-stored, a decay curve is meaningless, so log-only (µg)
    ('b12', 'none', '{}'::jsonb, 'Vitamin B12', NULL, 'complement', 'µg', 1000.0),
    ('l-theanine', 'none', '{}'::jsonb, 'L-theanine', NULL, 'complement', 'mg', 1.0),
    ('paracetamol', 'bateman', '{"half_life_hours": 2.5, "absorption_half_life_hours": 0.3}'::jsonb, 'Paracetamol', 'gold', 'pharma', 'mg', 1.0),
    ('ibuprofen', 'bateman', '{"half_life_hours": 2.2, "absorption_half_life_hours": 0.5}'::jsonb, 'Ibuprofen', 'gold', 'pharma', 'mg', 1.0),
    -- alcohol is roughly zero-order, so the first-order model doesn't fit: log-only (g)
    ('alcohol', 'none', '{}'::jsonb, 'Alcohol', NULL, 'recreational', 'g', 0.001)
) AS v (name, model_family, params, label, color, category, unit, unit_per_mg)
WHERE NOT EXISTS (SELECT 1 FROM substance.catalog);

-- Deliberately no 'dual_peak' or 'flip_flop' row.
--
-- Both families are real and supported by the model, and both are covered by
-- the test suite with its own fixtures, so an empty example here costs no
-- coverage. They are absent because the obvious examples of each are an
-- extended-release stimulant and an injected depot ester, and a catalog naming
-- those has disclosed something about whoever wrote it.
--
-- The tempting fix is to substitute some other drug from each family. Resist it
-- unless you have read the pharmacokinetics and can cite them: a plausible
-- looking half-life that nobody fitted is worse than an absent row, because the
-- curve it draws looks exactly as confident as a correct one.

INSERT INTO substance.templates (name, substance, dose_mg, label)
SELECT * FROM (VALUES
    -- caffeine sources
    ('espresso', 'caffeine', 80.0, 'Espresso'),
    ('coffee-mug', 'caffeine', 100.0, 'Coffee (mug)'),
    ('tea-black', 'caffeine', 45.0, 'Black tea (cup)'),
    ('energy-drink-250', 'caffeine', 80.0, 'Energy drink 250 ml'),
    ('energy-drink-500', 'caffeine', 160.0, 'Energy drink 500 ml'),
    -- EU cola is ~9.6 mg caffeine/100 ml, so a 330 ml can is ~32 mg
    ('cola-330', 'caffeine', 32.0, 'Cola 330 ml'),
    -- sleep
    ('melatonin-5', 'melatonin', 5.0, 'Melatonin 5 mg (subl.)'),
    ('melatonin-2-5', 'melatonin', 2.5, 'Melatonin 2.5 mg (subl.)'),
    -- pharma
    ('paracetamol-500', 'paracetamol', 500.0, 'Paracetamol 500 mg'),
    ('paracetamol-1000', 'paracetamol', 1000.0, 'Paracetamol 1 g'),
    ('ibuprofen-400', 'ibuprofen', 400.0, 'Ibuprofen 400 mg'),
    ('ibuprofen-600', 'ibuprofen', 600.0, 'Ibuprofen 600 mg'),
    -- supplements
    ('b12', 'b12', 5.0, 'B12 5000 µg'),
    ('l-theanine-200', 'l-theanine', 200.0, 'L-theanine 200 mg'),
    ('alcohol', 'alcohol', 12000.0, 'Standard drink (~12 g)')
) AS v (name, substance, dose_mg, label)
WHERE NOT EXISTS (SELECT 1 FROM substance.templates);

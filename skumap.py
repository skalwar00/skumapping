-- 1. Purane Triggers aur Functions ko delete karein (Conflict hatane ke liye)
DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
DROP FUNCTION IF EXISTS public.handle_new_user();

-- 2. Profiles table ko ensure karein (with correct structure)
CREATE TABLE IF NOT EXISTS public.profiles (
    id UUID REFERENCES auth.users PRIMARY KEY,
    is_pro BOOLEAN DEFAULT FALSE,
    plan_expiry DATE DEFAULT (CURRENT_DATE + interval '7 days'),
    whatsapp_no TEXT,
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- 3. Naya Trigger Function banayein
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS trigger AS $$
BEGIN
  INSERT INTO public.profiles (id, is_pro, plan_expiry)
  VALUES (new.id, false, (CURRENT_DATE + interval '7 days'));
  RETURN new;
EXCEPTION WHEN OTHERS THEN
  RETURN new; -- Agar profile nahi bhi bani, toh user creation fail nahi hoga
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- 4. Trigger activate karein
CREATE TRIGGER on_auth_user_created
  AFTER INSERT ON auth.users
  FOR EACH ROW EXECUTE PROCEDURE public.handle_new_user();

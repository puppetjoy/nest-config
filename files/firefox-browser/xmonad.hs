import XMonad
import qualified XMonad.StackSet as W
import System.Environment (lookupEnv)
import XMonad.Hooks.ManageDocks (docks, avoidStruts)
import XMonad.Hooks.EwmhDesktops (ewmh)
import Data.Monoid (All(..))

-- Only the local owner desktop sends this message after exact native identity
-- validation. Do not turn ordinary browser activation requests into focus theft.
ownerFocus :: Event -> X All
ownerFocus ClientMessageEvent { ev_message_type = message, ev_data = target:_ } = do
  expected <- getAtom "_NEST_OWNER_FOCUS"
  stack <- gets windowset
  let window = fromIntegral target
  if message == expected && window `elem` W.allWindows stack
    then windows (W.focusWindow window)
    else pure ()
  pure (All True)
ownerFocus _ = pure (All True)

main :: IO ()
main = do
  protocol <- lookupEnv "FIREFOX_CONTROL_PROTOCOL"
  xmonad $ ewmh $ docks def
    { borderWidth        = 0
    , focusFollowsMouse  = True
    , layoutHook         = avoidStruts Full
    -- New task windows stay behind the owner's current focus. Native transient
    -- dialogs keep the normal manage hook; only the owner panel changes focus.
    , manageHook         = manageHook def <+> (if protocol == Just "firefox-windows-v3"
        then resource =? "Navigator" --> doF W.focusDown else mempty)
    , handleEventHook    = ownerFocus <+> handleEventHook def
    , startupHook        = spawn "xsetroot -solid black"
    , terminal           = "false"
    }

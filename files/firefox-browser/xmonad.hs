import XMonad

main :: IO ()
main = xmonad def
  { borderWidth        = 0
  , focusFollowsMouse  = True
  , layoutHook         = Full
  , startupHook        = spawn "xsetroot -solid black"
  , terminal           = "false"
  }

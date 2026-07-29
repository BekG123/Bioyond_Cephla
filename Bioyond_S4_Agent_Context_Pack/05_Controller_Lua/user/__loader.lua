 package.path = "../user/?.lua"
 require("__sys")
 require("data")
 require("mod001Socket1")
 require("mod001Socket2")
 require("mod002Init")
 require("mod003End")
 require("mod004Phome")
 require("mod_InputPoint")
 require("mod_Pick1")
 require("mod_Pick2")
 require("mod_Place1")
 require("mod_Place2")
 require("errhandler")
 require("main")
function __loader()
 main()
end

function __errhandler()
 PRINT(debug.traceback())
 errhandler()
end
